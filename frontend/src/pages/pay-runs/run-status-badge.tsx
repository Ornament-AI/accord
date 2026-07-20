import type { VariantProps } from "class-variance-authority";

import { Badge } from "@/components/ui/badge";
import type { badgeVariants } from "@/components/ui/badge-variants";
import { statusLabel } from "@/lib/payroll-display";

type BadgeVariant = NonNullable<VariantProps<typeof badgeVariants>["variant"]>;

const STATUS_VARIANTS: Record<string, BadgeVariant> = {
	draft: "muted",
	calculating: "processing",
	calculated: "info",
	submitted: "review",
	approved: "success",
	rejected: "destructive",
	posted: "default",
	reversed: "warning",
};

export function RunStatusBadge({ status }: { status: string }) {
	const variant = STATUS_VARIANTS[status] ?? "muted";
	return (
		<Badge variant={variant} data-testid="run-status-badge" data-status={status}>
			{statusLabel(status)}
		</Badge>
	);
}
