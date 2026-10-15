// Shown while an account holds an old temporary password.
import { useAuth } from "../auth";
import { PasswordForm } from "./Profile";
import { Button } from "../buttons";

// Shown instead of the app while the account holds a temporary password.
export default function ChangePassword() {
  const { user, setUser, signOut } = useAuth();
  return (
    <div className="gate">
      <div className="panel">
        <div className="mark">S</div>
        <h1>Choose a new password</h1>
        <p className="lede">
          An admin reset the password for {user.email}. Enter the temporary
          password you were given, then one of your own.
        </p>
        <PasswordForm temporary onDone={setUser} />
        <div className="swap">
          <Button tone="link" onClick={signOut}>Sign out</Button>
        </div>
      </div>
    </div>
  );
}
