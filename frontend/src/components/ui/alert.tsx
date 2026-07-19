import { InfoIcon as Info } from "@phosphor-icons/react/dist/csr/Info";
import { WarningIcon as AlertTriangle } from "@phosphor-icons/react/dist/csr/Warning";
import { WarningCircleIcon as AlertCircle } from "@phosphor-icons/react/dist/csr/WarningCircle";
import { cva, type VariantProps } from "class-variance-authority";
import type * as React from "react";

import { cn } from "@/lib/utils";

const alertVariants = cva("relative w-full rounded-lg border px-4 py-3 text-sm group/alert", {
	variants: {
		variant: {
			default: "bg-card text-card-foreground border-border",
			destructive: "bg-destructive/5 dark:bg-destructive/10 border-destructive/20 text-destructive",
			warning:
				"bg-amber-500/5 dark:bg-amber-500/10 border-amber-500/20 text-amber-600 dark:text-amber-500",
		},
	},
	defaultVariants: {
		variant: "default",
	},
});

// Derive AlertVariant type from the alertVariants constant
type AlertVariant = NonNullable<VariantProps<typeof alertVariants>["variant"]>;

const variantIcons: Record<AlertVariant, React.ReactNode> = {
	default: <Info size={18} />,
	destructive: <AlertCircle size={18} />,
	warning: <AlertTriangle size={18} />,
};

interface AlertProps extends React.ComponentProps<"div">, VariantProps<typeof alertVariants> {
	/** Hide the default icon */
	hideIcon?: boolean;
}

function Alert({ className, variant, hideIcon, children, ...props }: AlertProps) {
	const effectiveVariant = variant ?? "default";
	const showIcon = !hideIcon;

	return (
		<div
			data-slot="alert"
			role="alert"
			className={cn(alertVariants({ variant }), className)}
			{...props}
		>
			<div className="flex gap-3">
				{showIcon && <div className="flex-shrink-0 mt-0.5">{variantIcons[effectiveVariant]}</div>}
				<div className="flex-1 min-w-0">{children}</div>
			</div>
		</div>
	);
}

function AlertTitle({ className, ...props }: React.ComponentProps<"div">) {
	return (
		<div data-slot="alert-title" className={cn("font-medium leading-snug", className)} {...props} />
	);
}

function AlertDescription({ className, ...props }: React.ComponentProps<"div">) {
	return (
		<div
			data-slot="alert-description"
			className={cn(
				"mt-1 text-sm opacity-90 [&_p:not(:last-child)]:mb-2 [&_ul]:mt-2 [&_ul]:space-y-1 [&_li]:leading-relaxed",
				className,
			)}
			{...props}
		/>
	);
}

function AlertAction({ className, ...props }: React.ComponentProps<"div">) {
	return (
		<div
			data-slot="alert-action"
			className={cn("absolute top-2.5 right-3", className)}
			{...props}
		/>
	);
}

export { Alert, AlertAction, AlertDescription, AlertTitle };
