# Weather-aware truck routing

Live site: https://truck-routing-beta.vercel.app

A React and Django app that compares three truck routes and recommends the safest one for a given departure time and load weight.

The driver enters an origin, a destination, a departure date and time, and a load weight in pounds. The server asks OpenRouteService for three heavy-goods routes, samples the forecast along each route, and ranks them with the Spotter risk rules.

## How a trip is scored

Checkpoints are placed every 10 miles on trips under 100 miles, every 25 miles under 300 miles, and every 50 miles after that. Weather at each checkpoint is the forecast hour closest to the truck’s estimated arrival.

Wind, rain, and snow are each classified as Low, Moderate, High, Severe, or No Travel. The worst of the three is the checkpoint risk. Load weight changes the wind result:

- 55 mph or more is No Travel for any load
- 45–54 mph and more than 30,000 lb is No Travel
- 35–44 mph and more than 40,000 lb is Severe

| Condition | Low | Moderate | High | Severe | No Travel |
| --- | --- | --- | --- | --- | --- |
| Wind | under 25 mph | 25–34 | 35–44 | 45–54 | 55 mph or more |
| Rain | under 0.10 in/hr | 0.10–0.25 | 0.25–0.50 | 0.50–1.00 | over 1.00 |
| Snow | under 0.5 in/hr | 0.5–1.0 | 1.0–2.0 | 2.0–3.0 | over 3.0 |

The recommended route is the one with the fewest no-travel miles, then the fewest severe miles, then the fewest high miles, then the lowest average risk, then the shortest time.

The map draws the three routes and the checkpoints. The colored band is a 0–48 hour forecast for the corridor. That forecast is downloaded once with the trip. Moving the slider only changes which hour is shown.

## Run it locally

Python 3.12 or newer, Node.js, and an OpenRouteService API key.

```bash
pip install -r requirements.txt
```

Create a `.env` file in this folder:

```
ORS_API_KEY=your-key-here
```

Start the API:

```bash
python manage.py runserver 127.0.0.1:8000
```

In a second terminal:

```bash
cd web
npm install
npm run dev -- --port 5174 --strictPort
```

Open http://localhost:5174. On Windows PowerShell, if `npm` is blocked, use `npm.cmd`.

Weather comes from Open-Meteo and does not need a key. Map tiles are OpenStreetMap.

## Project layout

- `routes/views.py` — geocoding, the three routes, risk scoring, and the corridor forecast
- `web/` — the React form, map, and forecast slider
- `.env` — the routing key, kept out of git
