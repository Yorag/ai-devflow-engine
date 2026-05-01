import { Link } from "react-router-dom";

export function HomePage(): JSX.Element {
  return (
    <section className="page-surface page-surface--home" aria-labelledby="home-heading">
      <div className="page-kicker">Function one</div>
      <h1 id="home-heading">Requirement delivery flow engine</h1>
      <p className="page-lede">
        Open the console to manage project sessions, track workflow runs, and
        review delivery outcomes from one workspace.
      </p>
      <Link className="primary-link" to="/console">
        Open console
      </Link>
    </section>
  );
}
