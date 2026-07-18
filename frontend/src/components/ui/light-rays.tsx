import { type CSSProperties, useMemo } from "react";

import { m } from "@/lib/motion";
import { cn } from "@/lib/utils";

interface LightRaysProps extends React.HTMLAttributes<HTMLDivElement> {
	ref?: React.Ref<HTMLDivElement>;
	count?: number;
	color?: string;
	blur?: number;
	speed?: number;
	length?: string;
}

type LightRay = {
	id: string;
	left: number;
	rotate: number;
	width: number;
	swing: number;
	delay: number;
	duration: number;
	intensity: number;
};

function seededUnit(index: number, salt: number) {
	const value = Math.sin((index + 1) * 12.9898 + salt * 78.233) * 43758.5453;
	return value - Math.floor(value);
}

const createRays = (count: number, cycle: number): LightRay[] => {
	if (count <= 0) return [];

	return Array.from({ length: count }, (_, index) => {
		const left = 8 + seededUnit(index, 1) * 84;
		const rotate = -28 + seededUnit(index, 2) * 56;
		const width = 160 + seededUnit(index, 3) * 160;
		const swing = 0.8 + seededUnit(index, 4) * 1.8;
		const delay = seededUnit(index, 5) * cycle;
		const duration = cycle * (0.75 + seededUnit(index, 6) * 0.5);
		const intensity = 0.6 + seededUnit(index, 7) * 0.5;

		return {
			id: `${index}-${Math.round(left * 10)}`,
			left,
			rotate,
			width,
			swing,
			delay,
			duration,
			intensity,
		};
	});
};

const Ray = ({ left, rotate, width, swing, delay, duration, intensity }: LightRay) => {
	return (
		<m.div
			className="pointer-events-none absolute -top-[12%] left-[var(--ray-left)] h-[var(--light-rays-length)] w-[var(--ray-width)] origin-top -translate-x-1/2 rounded-full bg-gradient-to-b from-[color-mix(in_srgb,var(--light-rays-color)_70%,transparent)] to-transparent opacity-0 blur-[var(--light-rays-blur)]"
			style={
				{
					"--ray-left": `${left}%`,
					"--ray-width": `${width}px`,
				} as CSSProperties
			}
			initial={{ rotate: rotate }}
			animate={{
				opacity: [0, intensity, 0],
				rotate: [rotate - swing, rotate + swing, rotate - swing],
			}}
			transition={{
				duration: duration,
				repeat: Infinity,
				ease: "easeInOut",
				delay: delay,
				repeatDelay: duration * 0.1,
			}}
		/>
	);
};

export function LightRays({
	className,
	style,
	count = 7,
	color = "var(--light-rays-color)",
	blur = 36,
	speed = 14,
	length = "70vh",
	ref,
	...props
}: LightRaysProps) {
	const cycleDuration = Math.max(speed, 0.1);
	const rays = useMemo(() => createRays(count, cycleDuration), [count, cycleDuration]);

	return (
		<div
			ref={ref}
			className={cn(
				"pointer-events-none absolute inset-0 isolate overflow-hidden rounded-[inherit]",
				className,
			)}
			style={
				{
					"--light-rays-color": color,
					"--light-rays-blur": `${blur}px`,
					"--light-rays-length": length,
					...style,
				} as CSSProperties
			}
			{...props}
		>
			<div className="absolute inset-0 overflow-hidden">
				<div
					aria-hidden
					className="absolute inset-0 opacity-80"
					style={
						{
							background:
								"radial-gradient(circle at 20% 15%, color-mix(in srgb, var(--light-rays-color) 60%, transparent), transparent 60%)",
						} as CSSProperties
					}
				/>
				<div
					aria-hidden
					className="absolute inset-0 opacity-80"
					style={
						{
							background:
								"radial-gradient(circle at 80% 10%, color-mix(in srgb, var(--light-rays-color) 50%, transparent), transparent 65%)",
						} as CSSProperties
					}
				/>
				{rays.map((ray) => (
					<Ray key={ray.id} {...ray} />
				))}
			</div>
		</div>
	);
}
