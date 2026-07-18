import { useRender } from "@base-ui/react/use-render";
import type { VariantProps } from "class-variance-authority";
import type * as React from "react";

import { buttonVariants } from "@/components/ui/button-variants";
import { cn } from "@/lib/utils";

interface ButtonProps
	extends React.ButtonHTMLAttributes<HTMLButtonElement>,
		VariantProps<typeof buttonVariants> {
	ref?: React.Ref<HTMLButtonElement>;
	render?:
		| React.ReactElement
		| ((props: React.ButtonHTMLAttributes<HTMLButtonElement>) => React.ReactElement);
}

function Button({
	className,
	variant = "default",
	size = "default",
	render,
	...props
}: ButtonProps) {
	const mergedProps = {
		"data-slot": "button",
		"data-variant": variant,
		"data-size": size,
		className: cn(buttonVariants({ variant, size, className })),
		...props,
	};

	return useRender({
		render,
		defaultTagName: "button",
		props: mergedProps,
	});
}

export { Button };
