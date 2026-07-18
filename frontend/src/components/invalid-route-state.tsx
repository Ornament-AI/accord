import { Link } from "react-router";
import { EmptyState } from "@/components/empty-state";
import { Button } from "@/components/ui/button";

export function InvalidRouteState({
	title,
	description,
	returnTo,
	returnLabel,
}: {
	title: string;
	description: string;
	returnTo: string;
	returnLabel: string;
}) {
	return (
		<EmptyState
			className="app-material-level-1 app-border-level-1 border bg-card py-10"
			title={title}
			description={description}
		>
			<Button render={<Link to={returnTo} />} variant="outline">
				{returnLabel}
			</Button>
		</EmptyState>
	);
}
