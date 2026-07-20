import { Link } from "react-router";
import { AppLayout } from "@/components/app-layout";
import { EmptyState } from "@/components/empty-state";
import { Button } from "@/components/ui/button";

export default function NotFoundPage() {
	return (
		<AppLayout title="Page Not Found">
			<div className="flex min-h-0 flex-1 items-center justify-center p-6">
				<EmptyState
					className="app-material-level-1 app-border-level-1 max-w-md border bg-card p-8"
					title="Page Not Found"
					description="The page you requested does not exist."
				>
					<Button render={<Link to="/" />}>Return Home</Button>
				</EmptyState>
			</div>
		</AppLayout>
	);
}
