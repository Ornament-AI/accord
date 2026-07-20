import { cva } from "class-variance-authority";

export const badgeVariants = cva(
	"accord-motion-highlight h-5 gap-1 rounded-4xl border border-transparent px-2 py-0.5 text-xs font-medium has-data-[icon=inline-end]:pr-1.5 has-data-[icon=inline-start]:pl-1.5 [&>svg]:size-3! inline-flex items-center justify-center w-fit whitespace-nowrap shrink-0 [&>svg]:pointer-events-none focus-visible:border-ring focus-visible:ring-ring/35 focus-visible:ring-2 aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 aria-invalid:border-destructive overflow-hidden group/badge",
	{
		variants: {
			variant: {
				default: "bg-primary text-primary-foreground [a]:hover:bg-primary/80",
				secondary: "bg-secondary text-secondary-foreground [a]:hover:bg-secondary/80",
				destructive:
					"bg-destructive/10 [a]:hover:bg-destructive/20 focus-visible:ring-destructive/20 dark:focus-visible:ring-destructive/40 text-destructive dark:bg-destructive/20",
				outline:
					"border-border/38 text-foreground [a]:hover:bg-muted [a]:hover:text-muted-foreground dark:border-border",
				ghost: "hover:bg-muted hover:text-muted-foreground",
				link: "text-primary-text underline-offset-4 hover:underline",
				success: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400 dark:bg-emerald-500/20",
				warning: "bg-amber-500/15 text-amber-700 dark:text-amber-400 dark:bg-amber-500/20",
				info: "bg-lime-500/15 text-lime-700 dark:text-lime-400 dark:bg-lime-500/20",
				processing: "bg-green-500/15 text-green-700 dark:text-green-400 dark:bg-green-500/20",
				review: "bg-orange-500/15 text-orange-700 dark:text-orange-400 dark:bg-orange-500/20",
				muted: "bg-muted text-muted-foreground",
			},
		},
		defaultVariants: {
			variant: "default",
		},
	},
);
