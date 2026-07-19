import { MagnifyingGlassIcon as Search } from "@phosphor-icons/react/dist/csr/MagnifyingGlass";

import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

type DataSearchControlProps = {
	search: string | undefined;
	title: string;
	placeholder: string;
	onSearchChange: (search: string | undefined) => void;
	className?: string;
};

export function DataSearchControl({
	search,
	title,
	placeholder,
	onSearchChange,
	className,
}: DataSearchControlProps) {
	return (
		<div className={cn("relative w-full max-w-xs", className)}>
			<Search
				aria-hidden
				className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground"
			/>
			<Input
				aria-label={title}
				placeholder={placeholder}
				value={search ?? ""}
				onChange={(event) => {
					onSearchChange(event.target.value || undefined);
				}}
				className="pl-8"
			/>
		</div>
	);
}
