import { Link } from "@tanstack/react-router";

import { StatePanel } from "@/components/common/StatePanel";

export function NotFoundPage() {
  return (
    <StatePanel
      state="not_found"
      title="This surface does not exist."
      detail={
        <span className="flex items-center justify-center gap-4">
          <Link to="/" className="text-accent hover:underline">Research</Link>
          <Link to="/data" className="text-accent hover:underline">Browse data</Link>
        </span>
      }
    />
  );
}
