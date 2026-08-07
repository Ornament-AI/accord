export const DIALOG_CONTENT_CLASSNAMES = {
	/** Standard compact create/edit forms (sm:max-w-md). */
	compactForm: "flex max-h-[86dvh] flex-col gap-0 overflow-hidden p-0 sm:max-w-md",
	/** Standard forms (sm:max-w-lg). */
	form: "flex max-h-[86dvh] flex-col gap-0 overflow-hidden p-0 sm:max-w-lg",
	largeForm: "flex max-h-[86dvh] flex-col gap-0 overflow-hidden p-0 sm:max-w-4xl",
	wideForm: "flex max-h-[86dvh] flex-col gap-0 overflow-hidden p-0 sm:max-w-5xl",
	extraWideForm: "flex max-h-[88dvh] flex-col gap-0 overflow-hidden p-0 sm:max-w-6xl",
} as const;
