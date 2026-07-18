export const DIALOG_CONTENT_CLASSNAMES = {
	/** Standard compact create/edit forms (Atlas sm:max-w-md pattern). */
	compactForm: "flex max-h-[86dvh] flex-col gap-0 overflow-hidden p-0 sm:max-w-md",
	/** Standard forms (Atlas sm:max-w-lg pattern). */
	form: "flex max-h-[86dvh] flex-col gap-0 overflow-hidden p-0 sm:max-w-lg",
	largeForm: "flex max-h-[86dvh] flex-col gap-0 overflow-hidden p-0 sm:max-w-4xl",
	wideForm: "flex max-h-[86dvh] flex-col gap-0 overflow-hidden p-0 sm:max-w-5xl",
	extraWideForm: "flex max-h-[88dvh] flex-col gap-0 overflow-hidden p-0 sm:max-w-6xl",
} as const;
