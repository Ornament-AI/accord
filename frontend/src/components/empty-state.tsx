import type { ComponentProps, ComponentType, ReactNode, SVGProps } from "react";

import {
	Empty,
	EmptyContent,
	EmptyDescription,
	EmptyHeader,
	EmptyMedia,
	EmptyTitle,
} from "@/components/ui/empty";

type EmptyStateIcon = ComponentType<SVGProps<SVGSVGElement>>;

interface EmptyStateProps extends Omit<ComponentProps<typeof Empty>, "title"> {
	icon?: EmptyStateIcon;
	title: ReactNode;
	description?: ReactNode;
}

export function EmptyState({
	icon: Icon,
	title,
	description,
	children,
	...props
}: EmptyStateProps) {
	return (
		<Empty {...props}>
			<EmptyHeader>
				{Icon ? (
					<EmptyMedia variant="icon">
						<Icon aria-hidden="true" />
					</EmptyMedia>
				) : null}
				<EmptyTitle>{title}</EmptyTitle>
				{description !== undefined && description !== null ? (
					<EmptyDescription>{description}</EmptyDescription>
				) : null}
			</EmptyHeader>
			{children ? <EmptyContent>{children}</EmptyContent> : null}
		</Empty>
	);
}
