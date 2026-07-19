import { Toggle as TogglePrimitive } from "@base-ui/react/toggle";
import { ToggleGroup as ToggleGroupPrimitive } from "@base-ui/react/toggle-group";
import { Monitor, Moon, Sun } from "lucide-react";
import { SidebarMenuButton } from "@/components/ui/sidebar";
import type { Theme } from "@/lib/ui/providers/theme-provider";
import { useTheme } from "@/lib/ui/providers/theme-provider";
import { cn } from "@/lib/utils";

const themes = [
	{ value: "system" as const, icon: Monitor, label: "System Theme" },
	{ value: "light" as const, icon: Sun, label: "Light Theme" },
	{ value: "dark" as const, icon: Moon, label: "Dark Theme" },
];

interface ThemeSwitcherProps {
	className?: string;
	compact?: boolean;
}

export function ThemeSwitcher({ className, compact = false }: ThemeSwitcherProps) {
	const { theme, setTheme } = useTheme();

	const activeIndex = themes.findIndex((t) => t.value === theme);
	const activeTheme = themes[activeIndex] ?? themes[0];
	const nextTheme = themes[(activeIndex + 1) % themes.length] ?? themes[0];

	if (compact) {
		const ActiveIcon = activeTheme.icon;

		return (
			<SidebarMenuButton
				aria-label={`Theme: ${activeTheme.label}. Click to switch to ${nextTheme.label}`}
				tooltip={`Theme · ${activeTheme.label}`}
				className={cn("justify-center rounded-md bg-muted/90 hover:bg-sidebar-accent", className)}
				onClick={() => setTheme(nextTheme.value)}
			>
				<ActiveIcon size={14} />
				<span className="sr-only">
					Theme: {activeTheme.label}. Click to switch to {nextTheme.label}
				</span>
			</SidebarMenuButton>
		);
	}

	return (
		<ToggleGroupPrimitive
			value={[theme]}
			onValueChange={(values) => {
				if (values.length > 0) {
					setTheme(values[0] as Theme);
				}
			}}
			className={cn(
				"relative inline-flex items-center rounded-full bg-muted p-0.5",
				"ring-1 ring-border",
				className,
			)}
		>
			{/* Active indicator */}
			<div
				className="accord-motion-toggle-pill absolute top-0.5 bottom-0.5 rounded-full bg-background shadow-sm"
				style={{
					width: `calc((100% - 4px) / ${themes.length})`,
					transform: `translateX(calc(${activeIndex} * 100%))`,
				}}
			/>

			{themes.map(({ value, icon: Icon, label }) => (
				<TogglePrimitive
					key={value}
					value={value}
					aria-label={label}
					className={cn(
						"relative z-10 flex h-7 w-7 items-center justify-center rounded-full",
						"accord-motion-toggle-button",
						"text-muted-foreground hover:text-foreground data-[pressed]:text-foreground",
					)}
				>
					<Icon size={14} />
				</TogglePrimitive>
			))}
		</ToggleGroupPrimitive>
	);
}
