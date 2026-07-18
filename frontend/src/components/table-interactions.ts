export function isInteractiveRowTarget(
	target: EventTarget | null,
	row?: HTMLElement | null,
): boolean {
	if (!(target instanceof HTMLElement)) return false;
	const interactive = target.closest(
		'a,button,input,textarea,select,[role="button"],[role="menuitem"],[data-row-click-ignore]',
	);
	return Boolean(interactive && interactive !== row);
}
