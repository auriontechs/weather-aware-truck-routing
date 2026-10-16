import json
import math
import os
import time
from datetime import datetime, timedelta, timezone

import requests
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

ORS = 'https://api.openrouteservice.org'


def health(request):
    return JsonResponse({'ok': True, 'app': 'truck-routing'})


def geocode(text):
    response = requests.get(
        f'{ORS}/geocode/search',
        params={'text': text, 'size': 1},
        headers={'Authorization': os.environ['ORS_API_KEY']},
        timeout=20,
    )
    response.raise_for_status()
    lon, lat = response.json()['features'][0]['geometry']['coordinates']
    return [lon, lat]


def one_route(coordinates):
    response = requests.post(
        f'{ORS}/v2/directions/driving-hgv/geojson',
        json={'coordinates': coordinates},
        headers={'Authorization': os.environ['ORS_API_KEY']},
        timeout=30,
    )
    response.raise_for_status()
    feature = response.json()['features'][0]
    summary = feature['properties']['summary']
    return {
        'miles': round(summary['distance'] / 1609.34, 1),
        'hours': round(summary['duration'] / 3600, 2),
        'line': feature['geometry']['coordinates'],
    }


def drive(origin, destination):
    """Three ways: direct, then a middle point north of the line, then south."""
    mid_lon = (origin[0] + destination[0]) / 2
    mid_lat = (origin[1] + destination[1]) / 2
    via_points = [
        None,
        [mid_lon, mid_lat + 0.5],
        [mid_lon, mid_lat - 0.5],
    ]
    routes = []
    for via in via_points:
        coordinates = [origin, destination] if via is None else [origin, via, destination]
        try:
            routes.append(one_route(coordinates))
        except requests.RequestException:
            if via is None:
                raise
    if not routes:
        raise RuntimeError('No truck route was found for those places.')
    return routes


def test_route(request):
    """One sample truck route, so we can see the routing key works."""
    try:
        trip = drive(geocode('Dallas, Texas'), geocode('Houston, Texas'))[0]
    except Exception as error:
        return JsonResponse({'ok': False, 'error': str(error)}, status=502)
    return JsonResponse({
        'ok': True,
        'from': 'Dallas, Texas',
        'to': 'Houston, Texas',
        'miles': trip['miles'],
        'hours': trip['hours'],
    })


@csrf_exempt
def plan(request):
    """Accepts the driver's trip and returns one driving result."""
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'Use the form on the website.'}, status=405)
    try:
        body = json.loads(request.body.decode() or '{}')
        origin_text = str(body.get('origin', '')).strip()
        destination_text = str(body.get('destination', '')).strip()
        departure = str(body.get('departure', '')).strip()
        load_lb = float(body.get('load_lb') or 0)
        if not origin_text or not destination_text or not departure or load_lb <= 0:
            return JsonResponse({'ok': False, 'error': 'Fill in all four fields.'}, status=400)
        routes = drive(geocode(origin_text), geocode(destination_text))
        routes, heatmap = score_and_forecast(routes, departure, load_lb)
    except Exception as error:
        return JsonResponse({'ok': False, 'error': str(error)}, status=502)
    return JsonResponse({
        'ok': True,
        'from': origin_text,
        'to': destination_text,
        'departure': departure,
        'load_lb': load_lb,
        'recommendation': recommendation_text(routes),
        'routes': routes,
        'heatmap': heatmap,
    })


RISK_RANK = {'Low': 1, 'Moderate': 2, 'High': 3, 'Severe': 4, 'No Travel': 5}


def miles_between(a, b):
    lon1, lat1, lon2, lat2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(h))


def sample_every(miles):
    if miles < 100:
        return 10
    if miles < 300:
        return 25
    return 50


def sample_line(line, interval):
    points = [(line[0], 0.0)]
    walked = 0.0
    next_mark = interval
    previous = line[0]
    for coord in line[1:]:
        step = miles_between(previous, coord)
        walked += step
        while walked >= next_mark:
            over = walked - next_mark
            frac = 0 if step == 0 else 1 - over / step
            lon = previous[0] + (coord[0] - previous[0]) * frac
            lat = previous[1] + (coord[1] - previous[1]) * frac
            points.append(([lon, lat], round(next_mark, 1)))
            next_mark += interval
        previous = coord
    if points[-1][1] < walked:
        points.append((line[-1], round(walked, 1)))
    return points


def level_below(value, cuts):
    for name, cut in zip(('Low', 'Moderate', 'High', 'Severe'), cuts):
        if value < cut:
            return name
    return 'No Travel'


def wind_level(mph, load_lb):
    if mph >= 55:
        return 'No Travel'
    if 45 <= mph < 55 and load_lb > 30000:
        return 'No Travel'
    if 35 <= mph < 45 and load_lb > 40000:
        return 'Severe'
    return level_below(mph, (25, 35, 45, 55))


def worse(left, right):
    return left if RISK_RANK[left] >= RISK_RANK[right] else right


def risk_for(wind_mph, rain_in, snow_in, load_lb):
    return worse(
        wind_level(wind_mph, load_lb),
        worse(
            level_below(rain_in, (0.10, 0.25, 0.50, 1.00)),
            level_below(snow_in, (0.5, 1.0, 2.0, 3.0)),
        ),
    )


def bearing_deg(a, b):
    lon1, lat1, lon2, lat2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def offset_point(lon, lat, bearing, miles):
    distance = miles / 3958.8
    bearing = math.radians(bearing)
    lat1 = math.radians(lat)
    lon1 = math.radians(lon)
    lat2 = math.asin(
        math.sin(lat1) * math.cos(distance) + math.cos(lat1) * math.sin(distance) * math.cos(bearing)
    )
    lon2 = lon1 + math.atan2(
        math.sin(bearing) * math.sin(distance) * math.cos(lat1),
        math.cos(distance) - math.sin(lat1) * math.sin(lat2),
    )
    return [math.degrees(lon2), math.degrees(lat2)]


def corridor_points(routes, spacing=20, side_miles=10):
    """Points along each route, plus a band on either side, for the forecast map."""
    found = {}
    for route in routes:
        line = route['line']
        if len(line) < 2:
            continue
        walked = 0.0
        next_mark = 0.0
        previous = line[0]
        for coord in line[1:]:
            step = miles_between(previous, coord)
            if step == 0:
                previous = coord
                continue
            bearing = bearing_deg(previous, coord)
            while next_mark <= walked + step + 1e-6:
                frac = min(max((next_mark - walked) / step, 0), 1)
                lon = previous[0] + (coord[0] - previous[0]) * frac
                lat = previous[1] + (coord[1] - previous[1]) * frac
                for point in (
                    [lon, lat],
                    offset_point(lon, lat, bearing + 90, side_miles),
                    offset_point(lon, lat, bearing - 90, side_miles),
                ):
                    key = (round(point[1], 2), round(point[0], 2))
                    found.setdefault(key, point)
                next_mark += spacing
            walked += step
            previous = coord
    return list(found.values())


def point_key(lon, lat):
    return (round(lat, 2), round(lon, 2))


def fetch_hourly_batch(points):
    response = None
    for attempt in range(5):
        response = requests.get(
            'https://api.open-meteo.com/v1/forecast',
            params={
                'latitude': ','.join(f'{point[1]:.4f}' for point in points),
                'longitude': ','.join(f'{point[0]:.4f}' for point in points),
                'hourly': 'wind_speed_10m,precipitation,snowfall',
                'wind_speed_unit': 'mph',
                'precipitation_unit': 'inch',
                'timezone': 'UTC',
                'forecast_days': 7,
            },
            timeout=30,
        )
        if response.status_code == 429:
            time.sleep(2 * (attempt + 1))
            continue
        response.raise_for_status()
        data = response.json()
        return [data] if isinstance(data, dict) else data
    response.raise_for_status()


def fetch_forecasts(points):
    """Download the corridor forecast in a few calls. The slider does not call this again."""
    found = {}
    for start in range(0, len(points), 50):
        chunk = points[start:start + 50]
        for point, item in zip(chunk, fetch_hourly_batch(chunk)):
            found[point_key(point[0], point[1])] = item['hourly']
        if start + 50 < len(points):
            time.sleep(0.4)
    return found


def hour_times(hourly):
    return [datetime.fromisoformat(item).replace(tzinfo=timezone.utc) for item in hourly['time']]


def nearest_index(times, when):
    return min(range(len(times)), key=lambda index: abs(times[index] - when))


def reading_at(hourly, when):
    index = nearest_index(hour_times(hourly), when)
    return {
        'wind_mph': round(hourly['wind_speed_10m'][index] or 0, 1),
        'rain_in': round(hourly['precipitation'][index] or 0, 2),
        'snow_in': round((hourly['snowfall'][index] or 0) / 2.54, 2),
    }


def score_and_forecast(routes, departure_text, load_lb):
    departure = datetime.fromisoformat(departure_text)
    if departure.tzinfo is None:
        departure = departure.replace(tzinfo=timezone.utc)
    wanted = {}
    band = corridor_points(routes)
    for point in band:
        wanted.setdefault(point_key(point[0], point[1]), point)
    for route in routes:
        route['interval_miles'] = sample_every(route['miles'])
        route['samples'] = []
        for coord, mile in sample_line(route['line'], route['interval_miles']):
            eta = departure + timedelta(hours=route['hours'] * (mile / route['miles'] if route['miles'] else 0))
            route['samples'].append((coord, mile, eta))
            wanted.setdefault(point_key(coord[0], coord[1]), coord)
    forecasts = fetch_forecasts(list(wanted.values()))

    for route in routes:
        route['checkpoints'] = []
        for coord, mile, eta in route['samples']:
            weather = reading_at(forecasts[point_key(coord[0], coord[1])], eta)
            risk = risk_for(weather['wind_mph'], weather['rain_in'], weather['snow_in'], load_lb)
            route['checkpoints'].append({
                'mile': mile,
                'lat': round(coord[1], 5),
                'lon': round(coord[0], 5),
                'eta': eta.strftime('%Y-%m-%d %H:%M UTC'),
                'risk': risk,
                **weather,
            })
        severe = high = blocked = 0.0
        for index in range(1, len(route['checkpoints'])):
            segment = route['checkpoints'][index]['mile'] - route['checkpoints'][index - 1]['mile']
            risk = route['checkpoints'][index]['risk']
            if risk == 'No Travel':
                blocked += segment
            elif risk == 'Severe':
                severe += segment
            elif risk == 'High':
                high += segment
        ranks = [RISK_RANK[item['risk']] for item in route['checkpoints']]
        route['severe_miles'] = round(severe, 1)
        route['high_miles'] = round(high, 1)
        route['no_travel_miles'] = round(blocked, 1)
        route['average_risk'] = round(sum(ranks) / len(ranks), 2) if ranks else 1
        del route['samples']

    ordered = sorted(routes, key=lambda route: (
        route['no_travel_miles'], route['severe_miles'], route['high_miles'], route['average_risk'], route['hours'],
    ))
    for route in routes:
        route['recommended'] = route is ordered[0]

    sample_hourly = next(iter(forecasts.values()))
    times = hour_times(sample_hourly)
    indexes = [nearest_index(times, departure + timedelta(hours=hour)) for hour in range(49)]
    painted = []
    for point in band:
        hourly = forecasts[point_key(point[0], point[1])]
        risks = []
        for index in indexes:
            risks.append(RISK_RANK[risk_for(
                hourly['wind_speed_10m'][index] or 0,
                hourly['precipitation'][index] or 0,
                (hourly['snowfall'][index] or 0) / 2.54,
                load_lb,
            )])
        painted.append({'lat': round(point[1], 4), 'lon': round(point[0], 4), 'risks': risks})
    return routes, {'points': painted}


def recommendation_text(routes):
    winner = next(route for route in routes if route['recommended'])
    number = routes.index(winner) + 1
    return (
        f'Route {number} is recommended. It has the fewest no-travel miles, then the fewest severe miles, '
        f'then the fewest high miles, then the lowest average risk, then the shortest time.'
    )
