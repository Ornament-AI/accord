import { Toaster as Sonner, type ToasterProps } from "sonner";
import { useTheme } from "@/lib/ui/providers/theme-provider";

function Toaster({ ...props }: ToasterProps) {
	const { theme = "system" } = useTheme();

	return (
		<Sonner
			theme={theme as ToasterProps["theme"]}
			position="top-right"
			closeButton
			richColors
			expand
			gap={12}
			offset={16}
			toastOptions={{
				classNames: {
					toast: "group border-border shadow-lg",
					title: "text-foreground font-medium",
					description: "text-muted-foreground text-sm",
					closeButton: "left-0 right-auto border-border bg-background hover:bg-muted",
				},
			}}
			{...props}
		/>
	);
}

export { Toaster };
