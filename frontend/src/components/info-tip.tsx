import type { Icon as PhosphorIcon } from "@phosphor-icons/react";
import { InfoIcon as Info } from "@phosphor-icons/react/dist/csr/Info";
import type * as React from "react";
import type { ReactNode } from "react";

import { CardTitle } from "@/components/ui/card";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

type InfoTipProps = {
	text: string;
	ariaLabel?: string;
	className?: string;
	contentClassName?: string;
	side?: React.ComponentProps<typeof TooltipContent>["side"];
	icon?: PhosphorIcon;
	"data-testid"?: string;
};

export function InfoTip({
	text,
	ariaLabel = text,
	className,
	contentClassName,
	side = "top",
	icon: Icon = Info,
	"data-testid": dataTestId,
}: InfoTipProps) {
	const trigger = (
		<button
			type="button"
			aria-label={ariaLabel}
			data-testid={dataTestId}
			className={cn(
				"accord-motion-highlight -my-1 inline-flex size-6 shrink-0 touch-manipulation items-center justify-center rounded-full text-muted-foreground/60 hover:text-muted-foreground focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring/35",
				className,
			)}
		>
			<Icon className="size-3.5" aria-hidden="true" />
		</button>
	);

	return (
		<Tooltip>
			<TooltipTrigger render={trigger} />
			<TooltipContent side={side} className={contentClassName}>
				{text}
			</TooltipContent>
		</Tooltip>
	);
}

export function CardTitleWithInfo({
	children,
	info,
	className,
}: {
	children: ReactNode;
	info: string;
	className?: string;
}) {
	return (
		<CardTitle className={cn("inline-flex items-center gap-1.5", className)}>
			{children}
			<InfoTip text={info} />
		</CardTitle>
	);
}
