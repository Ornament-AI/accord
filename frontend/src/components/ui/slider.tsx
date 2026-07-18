import { Slider as SliderPrimitive } from "@base-ui/react/slider";

import { cn } from "@/lib/utils";

type SliderRangeValue = readonly number[];

interface SliderProps
	extends Omit<SliderPrimitive.Root.Props<SliderRangeValue>, "value" | "defaultValue"> {
	value?: SliderRangeValue;
	defaultValue?: SliderRangeValue;
	controlClassName?: string;
	trackClassName?: string;
	indicatorClassName?: string;
	thumbClassName?: string;
	getAriaLabel?: SliderPrimitive.Thumb.Props["getAriaLabel"];
	getAriaValueText?: SliderPrimitive.Thumb.Props["getAriaValueText"];
}

function Slider({
	className,
	controlClassName,
	trackClassName,
	indicatorClassName,
	thumbClassName,
	value,
	defaultValue,
	getAriaLabel,
	getAriaValueText,
	...props
}: SliderProps) {
	const values = value ?? defaultValue ?? [props.min ?? 0];
	const thumbKeys =
		values.length === 1
			? ["single"]
			: values.map((_, index) =>
					index === 0 ? "minimum" : index === 1 ? "maximum" : `thumb-${index}`,
				);

	return (
		<SliderPrimitive.Root
			data-slot="slider"
			className={cn(
				"group/slider relative flex w-full touch-none select-none items-center data-disabled:opacity-50",
				className,
			)}
			value={value}
			defaultValue={defaultValue}
			{...props}
		>
			<SliderPrimitive.Control
				data-slot="slider-control"
				className={cn("relative flex h-4 w-full items-center", controlClassName)}
			>
				<SliderPrimitive.Track
					data-slot="slider-track"
					className={cn(
						"relative h-1 w-full grow overflow-hidden rounded-full bg-muted-foreground/15",
						trackClassName,
					)}
				>
					<SliderPrimitive.Indicator
						data-slot="slider-indicator"
						className={cn(
							"absolute h-full rounded-full bg-foreground/45 transition-colors duration-200 ease-out",
							"group-hover/slider:bg-foreground/60 group-data-dragging/slider:bg-primary/75",
							indicatorClassName,
						)}
					/>
				</SliderPrimitive.Track>
				{values.map((_, index) => (
					<SliderPrimitive.Thumb
						key={thumbKeys[index]}
						data-slot="slider-thumb"
						index={index}
						getAriaLabel={getAriaLabel}
						getAriaValueText={getAriaValueText}
						className={cn(
							"block size-3 rounded-full bg-foreground/90 outline-none",
							"shadow-[0_1px_2px_oklch(0_0_0_/_0.15)] dark:shadow-[0_1px_2px_oklch(0_0_0_/_0.5)]",
							"transition-[transform,background-color] duration-150 ease-out",
							"hover:scale-110 hover:bg-foreground",
							"data-dragging:scale-110 data-dragging:bg-primary",
							"has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring/35",
							"disabled:pointer-events-none disabled:opacity-50",
							thumbClassName,
						)}
					/>
				))}
			</SliderPrimitive.Control>
		</SliderPrimitive.Root>
	);
}

export { Slider };
