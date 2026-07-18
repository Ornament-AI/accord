import * as React from "react";

type SidebarResizeOptions = {
	isMobile: boolean;
	state: "expanded" | "collapsed";
	clampWidth: (widthPx: number) => number;
	setIsResizing: (isResizing: boolean) => void;
	setSidebarWidthPx: (widthPx: number) => void;
};

export function useSidebarResize({
	isMobile,
	state,
	clampWidth,
	setIsResizing,
	setSidebarWidthPx,
}: SidebarResizeOptions) {
	const suppressClickRef = React.useRef(false);
	const cleanupResizeRef = React.useRef<(() => void) | null>(null);
	const cleanupResize = React.useCallback(() => {
		const cleanup = cleanupResizeRef.current;
		cleanupResizeRef.current = null;
		cleanup?.();
	}, []);

	React.useEffect(() => cleanupResize, [cleanupResize]);

	const onPointerDown = React.useCallback(
		(event: React.PointerEvent<HTMLElement>) => {
			if (event.defaultPrevented) return;
			if (isMobile || state !== "expanded") return;
			if (event.button !== 0) return;

			const sidebarRoot = event.currentTarget.closest(
				'[data-slot="sidebar"]',
			) as HTMLElement | null;
			const gapElement = sidebarRoot?.querySelector(
				'[data-slot="sidebar-gap"]',
			) as HTMLElement | null;
			const wrapperElement = sidebarRoot?.closest(
				'[data-slot="sidebar-wrapper"]',
			) as HTMLElement | null;
			const side = (sidebarRoot?.getAttribute("data-side") ?? "left") as "left" | "right";
			const startWidth = gapElement?.getBoundingClientRect().width ?? 0;

			if (!gapElement || !wrapperElement || startWidth <= 0) return;

			event.preventDefault();

			const startX = event.clientX;
			const originalUserSelect = document.body.style.userSelect;
			const originalCursor = document.body.style.cursor;
			let moved = false;
			let didResize = false;
			let latestWidthPx = clampWidth(startWidth);

			document.body.style.userSelect = "none";
			document.body.style.cursor = "ew-resize";
			setIsResizing(true);

			const handlePointerMove = (moveEvent: PointerEvent) => {
				const deltaX = moveEvent.clientX - startX;
				const signedDelta = side === "right" ? -deltaX : deltaX;
				const nextWidth = startWidth + signedDelta;

				if (Math.abs(deltaX) > 2) {
					moved = true;
					suppressClickRef.current = true;
				}

				latestWidthPx = clampWidth(nextWidth);
				didResize = true;
				wrapperElement.style.setProperty("--sidebar-width", `${latestWidthPx}px`);
			};

			const cleanup = () => {
				window.removeEventListener("pointermove", handlePointerMove);
				window.removeEventListener("pointerup", handlePointerUp);
				window.removeEventListener("pointercancel", handlePointerUp);
				document.body.style.userSelect = originalUserSelect;
				document.body.style.cursor = originalCursor;
				setIsResizing(false);
				cleanupResizeRef.current = null;
			};

			const handlePointerUp = () => {
				cleanup();
				if (didResize) {
					setSidebarWidthPx(latestWidthPx);
				}
				// Let the synthetic click generated after a drag get swallowed once.
				if (!moved) {
					suppressClickRef.current = false;
				}
			};

			cleanupResizeRef.current = cleanup;
			window.addEventListener("pointermove", handlePointerMove);
			window.addEventListener("pointerup", handlePointerUp);
			window.addEventListener("pointercancel", handlePointerUp);
		},
		[clampWidth, isMobile, setIsResizing, setSidebarWidthPx, state],
	);

	const shouldSuppressClick = React.useCallback(() => {
		if (!suppressClickRef.current) return false;
		suppressClickRef.current = false;
		return true;
	}, []);

	return { onPointerDown, shouldSuppressClick };
}
