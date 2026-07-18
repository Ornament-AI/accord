import type * as React from "react";

import { cn } from "@/lib/utils";

interface PageShellProps {
	className?: string;
	children?: React.ReactNode;
	"data-testid"?: string;
}

function PageShell({ className, children, "data-testid": testId }: PageShellProps) {
	return (
		<div
			data-slot="page-shell"
			className={cn("flex min-h-0 min-w-0 flex-1 flex-col gap-4 p-4 md:py-6 lg:px-6", className)}
			data-testid={testId}
		>
			{children}
		</div>
	);
}

function PageSection({ className, ...props }: React.ComponentProps<"section">) {
	return <section data-slot="page-section" className={cn("min-w-0", className)} {...props} />;
}

export { PageSection, PageShell };
