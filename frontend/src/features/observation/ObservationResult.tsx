import type { NowRequest, NowResult, TerrainCoverage } from '../../api/types'
import { SourceLink } from '../../components/SourceLink'

export function ObservationResult({ result, request, coverage }: { result: NowResult | null; request?: NowRequest; coverage?: TerrainCoverage | null }) {
  return (
    <section className="workspace-card" aria-labelledby="result-heading">
      <div className="card-heading">
        <h2 id="result-heading">Observation</h2>
        {result && (
          <span className={`data-badge ${result.meta.data_status}`}>
            {result.meta.data_status}
          </span>
        )}
      </div>
      {!result ? (
        <div className="unknown-result">
          <p>Choose a site and time, then request an observation.</p>
          <p>Sun visibility: Unknown · Earth visibility: Unknown</p>
          <p>Simultaneous availability: Unknown</p>
        </div>
      ) : (
        <>
          <p className="result-site">{result.site.name}</p>
          <p className="muted">
            {result.site.latitude}° latitude, {result.site.longitude}° east
            longitude (normalized)
          </p>
          <p>
            Observation time:{' '}
            <time dateTime={result.point.timestamp}>
              {result.point.timestamp} (UTC)
            </time>
          </p>
          <div className="table-scroll">
            <table className="observation-table">
              <caption>Returned observation values</caption>
              <thead>
                <tr>
                  <th>Body</th>
                  <th>Azimuth</th>
                  <th>Elevation</th>
                  <th>Horizon</th>
                  <th>Visible</th>
                  <th>Visibility margin</th>
                </tr>
              </thead>
              <tbody>
                {(['sun', 'earth'] as const).map((body) => (
                  <tr key={body}>
                    <th scope="row">{body === 'sun' ? 'Sun' : 'Earth'}</th>
                    <td>{result.point[body].azimuth_deg}°</td>
                    <td>{result.point[body].elevation_deg}°</td>
                    <td>{result.point[body].horizon_elevation_deg}°</td>
                    <td>{result.point[body].visible ? 'Yes' : 'No'}</td>
                    <td>{request?.visibility_margin_deg ?? 0}°</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="availability">
            Simultaneous availability:{' '}
            <strong>{result.point.is_golden_window ? 'Yes' : 'No'}</strong>
          </p>
          <p className="muted">
            This is a single instant; it does not establish a continuous window
            or a communication link budget.
          </p>
          <dl className="model-details">
            <dt>Horizon mode</dt>
            <dd>{result.meta.horizon_mode}</dd>
            {result.meta.horizon_mode === 'terrain' && (
              <>
                <dt>Terrain dataset</dt>
                <dd>{result.meta.terrain_dataset_id ?? 'Not reported'}</dd>
                {coverage?.resolution_m != null && <><dt>Terrain resolution</dt><dd>{coverage.resolution_m} m</dd></>}
                {coverage?.source_url && <><dt>Terrain source</dt><dd><SourceLink url={coverage.source_url}>Dataset source ↗</SourceLink></dd></>}
              </>
            )}
            <dt>Visibility margin</dt>
            <dd>{request?.visibility_margin_deg ?? 0}°</dd>
            <dt>Surface elevation</dt>
            <dd>{result.site.surface_elevation_m} m</dd>
            <dt>Observer height above surface</dt>
            <dd>{result.site.observer_height_m} m</dd>
            <dt>Model</dt>
            <dd>{result.meta.model_version}</dd>
            <dt>Result generated</dt>
            <dd>{result.meta.generated_at} (UTC)</dd>
          </dl>
          {(['sun', 'earth'] as const).some((body) => result.point[body].elevation_deg > 0 && !result.point[body].visible) && (
            <p className="muted">An object can be above the zero-degree reference and still be blocked by the terrain horizon or the selected visibility margin.</p>
          )}
          <h3>Scientific sources</h3>
          <ul className="source-list">
            {result.meta.sources.map((source, i) => (
              <li key={i}>
                <SourceLink url={source.url}>{source.name}</SourceLink>
                <p className="muted">
                  Version: {source.version ?? 'Not reported'} · Retrieved:{' '}
                  {source.fetched_at} (UTC)
                </p>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  )
}
