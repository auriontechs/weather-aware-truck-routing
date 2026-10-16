import { useState } from 'react'
import RouteMap from './RouteMap.jsx'
import './App.css'

const empty = { origin: '', destination: '', departure: '', load: '' }

export default function App() {
  const [form, setForm] = useState(empty)
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  function update(event) {
    setForm({ ...form, [event.target.name]: event.target.value })
  }

  async function submit(event) {
    event.preventDefault()
    setBusy(true)
    setError('')
    setResult(null)
    try {
      const response = await fetch('http://127.0.0.1:8000/api/plan/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: AbortSignal.timeout(60000),
        body: JSON.stringify({
          origin: form.origin,
          destination: form.destination,
          departure: form.departure,
          load_lb: Number(form.load),
        }),
      })
      const data = await response.json()
      if (!response.ok || !data.ok) throw new Error(data.error || 'Could not plan the trip')
      setResult(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="page">
      <h1>Weather-aware truck routing</h1>
      <p className="lead">Enter the trip. The server compares three routes by weather risk, then time.</p>
      <form onSubmit={submit} className="card">
        <label>
          Origin
          <input name="origin" value={form.origin} onChange={update} placeholder="Dallas, Texas" required />
        </label>
        <label>
          Destination
          <input name="destination" value={form.destination} onChange={update} placeholder="Houston, Texas" required />
        </label>
        <label>
          Departure
          <input name="departure" type="datetime-local" value={form.departure} onChange={update} required />
        </label>
        <label>
          Load weight (lb)
          <input name="load" type="number" min="1" value={form.load} onChange={update} placeholder="32000" required />
        </label>
        <button type="submit" disabled={busy}>{busy ? 'Planning…' : 'Plan trip'}</button>
      </form>
      {error && <p className="error">{error}</p>}
      {result && (
        <section className="card result">
          <h2>{result.from} → {result.to}</h2>
          <p>{result.recommendation}</p>
          <RouteMap routes={result.routes} departure={result.departure} heatmap={result.heatmap} />
          {result.routes.map((route, index) => (
            <p key={index}>
              Route {index + 1}{route.recommended ? ' (recommended)' : ''}: {route.miles} miles, {route.hours} hours.
              Severe {route.severe_miles} mi, high {route.high_miles} mi, average risk {route.average_risk}.
            </p>
          ))}
        </section>
      )}
    </main>
  )
}
