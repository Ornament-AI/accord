const PAGE_GLOW_RGB = "245, 158, 11";
const PAGE_GLOW_OPACITY = 0.35;

export function PageGlow() {
	return (
		<div
			data-testid="page-glow"
			className="pointer-events-none absolute -top-[var(--header-height)] left-0 h-[calc(250px_+_var(--header-height))] w-[350px] dark:h-[calc(350px_+_var(--header-height))] dark:w-[450px]"
			style={{
				background: `radial-gradient(ellipse at top left, rgba(${PAGE_GLOW_RGB}, ${PAGE_GLOW_OPACITY}), transparent 60%)`,
			}}
		/>
	);
}
