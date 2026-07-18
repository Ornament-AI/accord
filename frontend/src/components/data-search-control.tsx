import { Search } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { toolbarOutlineClassName } from "@/components/ui/button-variants";
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogHeader,
	DialogTitle,
	DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

type DataSearchControlProps = {
	search: string | undefined;
	title: string;
	description: string;
	placeholder: string;
	onSearchChange: (search: string | undefined) => void;
};

export function DataSearchControl({
	search,
	title,
	description,
	placeholder,
	onSearchChange,
}: DataSearchControlProps) {
	const [open, setOpen] = useState(false);
	const [draft, setDraft] = useState(search ?? "");

	const setSearchOpen = (nextOpen: boolean) => {
		setOpen(nextOpen);
		if (nextOpen) setDraft(search ?? "");
	};
	const applySearch = () => {
		const nextSearch = draft.trim();
		setDraft(nextSearch);
		onSearchChange(nextSearch || undefined);
		setOpen(false);
	};

	return (
		<Dialog open={open} onOpenChange={setSearchOpen}>
			<DialogTrigger
				render={
					<Button
						variant="outline"
						size="icon"
						aria-label={search ? `Search: ${search}` : "Search"}
						title={search ? `Search: ${search}` : "Search"}
						className={cn(toolbarOutlineClassName, "relative justify-center")}
					/>
				}
			>
				<Search className="size-4" />
				{search ? (
					<span className="absolute top-1.5 right-1.5 size-1.5 rounded-full bg-primary">
						<span className="sr-only">Active search: {search}</span>
					</span>
				) : null}
			</DialogTrigger>
			<DialogContent className="inset-0 top-0 left-0 h-dvh max-w-none translate-x-0 translate-y-0 rounded-none border-0 bg-background/96 p-6 shadow-none backdrop-blur-xl sm:max-w-none sm:p-8">
				<div className="mx-auto grid h-full w-full max-w-3xl grid-rows-[auto_1fr] gap-8 pt-[14dvh]">
					<DialogHeader className="text-left">
						<DialogTitle>{title}</DialogTitle>
						<DialogDescription className="sr-only">{description}</DialogDescription>
					</DialogHeader>
					<form
						className="flex flex-col gap-3 sm:flex-row"
						onSubmit={(event) => {
							event.preventDefault();
							applySearch();
						}}
					>
						<Input
							aria-label={title}
							placeholder={placeholder}
							value={draft}
							onChange={(event) => setDraft(event.target.value)}
							onKeyDown={(event) => {
								if (event.key === "Enter") {
									event.preventDefault();
									applySearch();
								}
							}}
							autoFocus
						/>
						<Button type="submit" className="sm:w-28">
							Search
						</Button>
						{search ? (
							<Button
								type="button"
								variant="outline"
								className="sm:w-24"
								onClick={() => {
									setDraft("");
									onSearchChange(undefined);
									setOpen(false);
								}}
							>
								Clear
							</Button>
						) : null}
					</form>
				</div>
			</DialogContent>
		</Dialog>
	);
}
