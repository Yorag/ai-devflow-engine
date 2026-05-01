export function ConsolePage(): JSX.Element {
  return (
    <section
      className="page-surface page-surface--console"
      aria-labelledby="console-heading"
    >
      <div className="page-kicker">Workspace</div>
      <h1 id="console-heading">AI delivery workspace</h1>
      <p className="page-lede">
        Project, session, run, and delivery views will appear here as the
        workflow surface comes online.
      </p>
      <dl className="baseline-list" aria-label="Workspace areas">
        <div>
          <dt>Projects</dt>
          <dd>Keep delivery work organized by project and active session.</dd>
        </div>
        <div>
          <dt>Runs</dt>
          <dd>
            Follow requirement analysis, design, implementation, and review
            progress.
          </dd>
        </div>
        <div>
          <dt>Delivery</dt>
          <dd>
            Review approvals, tool activity, test output, and delivery results.
          </dd>
        </div>
      </dl>
    </section>
  );
}
