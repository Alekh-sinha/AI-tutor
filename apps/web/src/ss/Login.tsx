import { SignIn } from "./auth";

/** The first screen for anybody who is not signed in: sign in with a Google account. Children who only join a class with a code never see it (they have their own entry). */
export function Login() {
  return (
    <div className="login-page">
      <div className="card login-card">
        <span className="mark hi">सा</span>
        <h1>Welcome to Seekho <b>Saathi</b></h1>
        <p className="sub">Sign in with your Google account to learn with your AI teacher.</p>
        <SignIn />
        <p className="login-note">Free lessons can be watched by everyone who signs in. Live classes and lesson creation need approval from the admin; your request is sent automatically when you sign in.</p>
        <a className="login-join" href="/?join=1">Joining a class with a code? Enter it here</a>
      </div>
    </div>
  );
}
