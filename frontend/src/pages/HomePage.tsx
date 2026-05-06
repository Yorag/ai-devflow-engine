import { Link } from "react-router-dom";

import deliveryFlowUrl from "../../../assets/agent-delivery-flow.svg";

const docsUrl = "https://github.com/Yorag/ai-devflow-engine#readme";

const capabilities = [
  {
    title: "Preserve intent",
    body: "Requirements, constraints, and acceptance criteria stay attached to the run.",
  },
  {
    title: "Review before code",
    body: "Plans and validation appear before workspace changes.",
  },
  {
    title: "Record delivery",
    body: "Tests, review, approvals, and delivery result remain connected.",
  },
];

const stages = [
  {
    name: "Requirement",
    body: "Capture intent.",
  },
  {
    name: "Design",
    body: "Shape the plan.",
  },
  {
    name: "Code",
    body: "Change the workspace.",
  },
  {
    name: "Test",
    body: "Collect evidence.",
  },
  {
    name: "Review",
    body: "Check the result.",
  },
  {
    name: "Delivery",
    body: "Record the output.",
  },
];

const controlEvents = [
  "Approvals",
  "Tool confirmations",
  "Retry",
  "Rollback",
  "Delivery result",
];

export function HomePage(): JSX.Element {
  return (
    <div className="home-site">
      <header className="home-nav">
        <a className="home-nav__brand" href="#top">
          AI DevFlow Engine
        </a>
        <nav className="home-nav__links" aria-label="Website sections">
          <a href="#overview">Overview</a>
          <a href="#flow">Flow</a>
          <a href="#control">Control</a>
          <a href="#start">Start</a>
        </nav>
        <div className="home-nav__actions">
          <a className="home-link" href={docsUrl}>
            Docs
          </a>
          <Link className="home-button home-button--compact" to="/console">
            Open Console
          </Link>
        </div>
      </header>

      <section
        id="top"
        className="home-hero"
        aria-label="Website introduction"
      >
        <div className="home-hero__copy">
          <p className="home-eyebrow">Local-first AI delivery workflow</p>
          <h1>Make delivery work traceable.</h1>
          <p className="home-hero__lede">
            AI DevFlow Engine turns requirements, plans, tests, review, and
            delivery into one visible pipeline.
          </p>
          <div className="home-actions">
            <Link className="home-button" to="/console">
              Open Console
            </Link>
            <a className="home-button home-button--secondary" href="#flow">
              View Flow
            </a>
          </div>
        </div>

        <figure className="home-product-visual">
          <img
            src={deliveryFlowUrl}
            alt="AI DevFlow Engine delivery flow"
          />
        </figure>
      </section>

      <section
        id="overview"
        className="home-section home-overview"
        aria-labelledby="overview-heading"
      >
        <div className="home-section__heading home-section__heading--centered">
          <p className="home-eyebrow">Overview</p>
          <h2 id="overview-heading">Built for the work between prompt and delivery.</h2>
        </div>
        <div className="home-capability-row">
          {capabilities.map((capability) => (
            <article className="home-capability" key={capability.title}>
              <h3>{capability.title}</h3>
              <p>{capability.body}</p>
            </article>
          ))}
        </div>
      </section>

      <section id="flow" className="home-section home-flow" aria-labelledby="flow-heading">
        <div className="home-section__heading home-section__heading--centered">
          <p className="home-eyebrow">Flow</p>
          <h2 id="flow-heading">One path, six visible stages.</h2>
          <p>
            Each stage hands off a clear artifact, so the next step inherits
            context instead of guessing.
          </p>
        </div>
        <div className="home-stage-rail">
          {stages.map((stage) => (
            <article className="home-stage" key={stage.name}>
              <h3>{stage.name}</h3>
              <p>{stage.body}</p>
            </article>
          ))}
        </div>
      </section>

      <section
        id="control"
        className="home-section home-control"
        aria-labelledby="control-heading"
      >
        <div className="home-section__heading home-section__heading--centered">
          <p className="home-eyebrow">Control</p>
          <h2 id="control-heading">Human control stays in the workflow.</h2>
          <p>
            Approvals, tool confirmations, retry, rollback, and delivery result
            are workflow events, not notes outside the system.
          </p>
        </div>
        <ul className="home-event-row" aria-label="Workflow control events">
          {controlEvents.map((event) => (
            <li key={event}>{event}</li>
          ))}
        </ul>
      </section>

      <section id="start" className="home-section home-start" aria-labelledby="start-heading">
        <p className="home-eyebrow">Start</p>
        <h2 id="start-heading">Run the workflow from the console.</h2>
        <p>
          Create sessions, review stages, approve controls, and inspect
          delivery output from one workspace.
        </p>
        <div className="home-actions home-actions--centered">
          <Link className="home-button" to="/console">
            Open Console
          </Link>
          <a
            className="home-button home-button--secondary"
            href={docsUrl}
          >
            Read Documentation
          </a>
        </div>
      </section>
    </div>
  );
}
