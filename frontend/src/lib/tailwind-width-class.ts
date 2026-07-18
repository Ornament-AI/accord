export function hasTailwindWidthClass(className?: string): boolean {
	return className?.split(/\s+/).some((name) => /(?:^|:)!?w-/.test(name)) ?? false;
}
