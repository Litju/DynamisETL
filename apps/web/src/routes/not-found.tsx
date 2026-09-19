import { Link } from "@tanstack/react-router";

import { StatePanel } from "@/components/common/StatePanel";

export function NotFoundPage() {
  return (
    <StatePanel
      state="unavailable"
      title="This surface does not exist."
      detail={
        <Link to="/catalog" className="text-accent">
          Return to the catalog
        </Link>
      }
    />
  );
}
