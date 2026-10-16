import { useEffect, useRef, useState } from 'react'
import L from 'leaflet'
import { CircleMarker, MapContainer, Polyline, Popup, TileLayer, useMap } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'

const ROUTE_COLOR = ['#1565c0', '#6a1b9a', '#00838f']
const RISK_COLOR = {
  Low: '#1b7f3a',
  Moderate: '#c4a000',
  High: '#e07a00',
  Severe: '#c62828',
  'No Travel': '#4a148c',
}
const RANK_COLOR = ['#1b7f3a', '#1b7f3a', '#c4a000', '#e07a00', '#c62828', '#4a148c']
const RANK_NAME = ['', 'Low', 'Moderate', 'High', 'Severe', 'No Travel']

function HeatLayer({ points, hour }) {
  const map = useMap()
  const markers = useRef([])

  useEffect(() => {
    const group = L.layerGroup().addTo(map)
    markers.current = points.map((point) =>
      L.circle([point.lat, point.lon], {
        radius: 14000,
        stroke: false,
        fillColor: RANK_COLOR[point.risks[hour]] || RANK_COLOR[1],
        fillOpacity: 0.42,
      }).addTo(group),
    )
    return () => {
      group.remove()
      markers.current = []
    }
  }, [map, points])

  useEffect(() => {
    markers.current.forEach((marker, index) => {
      marker.setStyle({ fillColor: RANK_COLOR[points[index].risks[hour]] || RANK_COLOR[1] })
    })
  }, [hour, points])

  return null
}

function forecastLabel(departure, hour) {
  const text = departure.length === 16 ? `${departure}:00Z` : departure
  const time = new Date(text)
  if (Number.isNaN(time.getTime())) return `Hour ${hour}`
  time.setUTCHours(time.getUTCHours() + hour)
  return `${time.toISOString().slice(0, 16).replace('T', ' ')} UTC`
}

function Fit({ positions }) {
  const map = useMap()
  useEffect(() => {
    if (positions.length) map.fitBounds(positions, { padding: [28, 28] })
  }, [map, positions])
  return null
}

export default function RouteMap({ routes, departure, heatmap }) {
  const [hour, setHour] = useState(0)
  useEffect(() => {
    setHour(0)
  }, [heatmap])
  if (!routes?.[0]?.line) return null
  const positions = routes.flatMap((route) => route.line.map(([lon, lat]) => [lat, lon]))
  const points = heatmap?.points || []
  const worst = points.length ? Math.max(...points.map((point) => point.risks[hour] || 1)) : 1

  return (
    <div className="map">
      <MapContainer center={[31.5, -96.1]} zoom={6} scrollWheelZoom>
        <TileLayer
          attribution='&copy; OpenStreetMap'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <Fit positions={positions} />
        {points.length > 0 && <HeatLayer points={points} hour={hour} />}
        {routes.map((route, index) => (
          <Polyline
            key={`line-${index}`}
            positions={route.line.map(([lon, lat]) => [lat, lon])}
            pathOptions={{
              color: ROUTE_COLOR[index % ROUTE_COLOR.length],
              weight: route.recommended ? 6 : 4,
              opacity: 0.85,
            }}
          />
        ))}
        {routes.map((route, index) =>
          route.checkpoints.map((point) => (
            <CircleMarker
              key={`${index}-${point.mile}`}
              center={[point.lat, point.lon]}
              radius={route.recommended ? 8 : 6}
              pathOptions={{
                color: '#fff',
                weight: 2,
                fillColor: RISK_COLOR[point.risk] || '#333',
                fillOpacity: 1,
              }}
            >
              <Popup>
                <strong>Route {index + 1}</strong>
                <br />
                Mile {point.mile} · {point.risk}
                <br />
                Arrives {point.eta}
                <br />
                Wind {point.wind_mph} mph · rain {point.rain_in} in/hr · snow {point.snow_in} in/hr
              </Popup>
            </CircleMarker>
          )),
        )}
      </MapContainer>
      {points.length > 0 && (
        <label className="slider">
          Forecast hour {hour} of 48 · {forecastLabel(departure, hour)} · worst risk {RANK_NAME[worst]}
          <input
            type="range"
            min="0"
            max="48"
            step="1"
            value={hour}
            onChange={(event) => setHour(Number(event.target.value))}
          />
        </label>
      )}
      <p className="legend">
        {routes.map((route, index) => (
          <span key={index}>
            <i style={{ background: ROUTE_COLOR[index % ROUTE_COLOR.length] }} />
            Route {index + 1}{route.recommended ? ' (recommended)' : ''}
          </span>
        ))}
        {Object.entries(RISK_COLOR).map(([name, color]) => (
          <span key={name}>
            <i className="dot" style={{ background: color }} />
            {name}
          </span>
        ))}
      </p>
    </div>
  )
}
