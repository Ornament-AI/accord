import type { VariantProps } from "class-variance-authority";

import type { badgeVariants } from "@/components/ui/badge-variants";

type BadgeVariant = NonNullable<VariantProps<typeof badgeVariants>["variant"]>;

/** Map audit command families to existing badge variants. */
export function commandBadgeVariant(command: string): BadgeVariant {
	if (command.startsWith("payroll_run.")) return "info";
	if (command.startsWith("artifact.")) return "warning";
	if (
		command.startsWith("auth.") ||
		command.startsWith("session.") ||
		command === "login" ||
		command === "logout"
	) {
		return "review";
	}
	return "secondary";
}
