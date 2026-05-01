export function ConsolePage(): JSX.Element {
  return (
    <section
      className="page-surface page-surface--console"
      aria-labelledby="console-heading"
    >
      <div className="page-kicker">Console baseline</div>
      <h1 id="console-heading">AI delivery workspace</h1>
      <p className="page-lede">
        React SPA baseline is ready for feature slices.
      </p>
      <dl className="baseline-list" aria-label="F0.1 baseline scope">
        <div>
          <dt>Routing</dt>
          <dd>Home and console routes are mounted through React Router.</dd>
        </div>
        <div>
          <dt>Data layer</dt>
          <dd>TanStack Query provider is available to later API slices.</dd>
        </div>
        <div>
          <dt>Design tone</dt>
          <dd>
            Restrained product workspace UI, prepared for dense workflow views.
          </dd>
        </div>
      </dl>
    </section>
  );
}
