import { Link } from "react-router-dom";

export function HomePage(): JSX.Element {
  return (
    <section className="page-surface page-surface--home" aria-labelledby="home-heading">
      <div className="page-kicker">Function one baseline</div>
      <h1 id="home-heading">Requirement delivery flow engine</h1>
      <p className="page-lede">
        Start from the console route to continue building the project, session,
        run, and narrative workspace slices.
      </p>
      <Link className="primary-link" to="/console">
        Open console
      </Link>
    </section>
  );
}
