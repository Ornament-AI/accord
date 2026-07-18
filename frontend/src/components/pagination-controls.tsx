import {
	Pagination,
	PaginationContent,
	PaginationEllipsis,
	PaginationItem,
	PaginationLink,
	PaginationNext,
	PaginationPrevious,
} from "@/components/ui/pagination";
import { cn } from "@/lib/utils";

type PaginationRangeItem =
	| {
			type: "page";
			page: number;
	  }
	| {
			type: "ellipsis";
			key: string;
	  };

type PaginationControlsProps = {
	page: number;
	totalPages: number;
	onPageChange: (page: number) => void;
	className?: string;
	compact?: boolean;
	disabled?: boolean;
};

function clampPage(page: number, totalPages: number) {
	return Math.min(Math.max(1, page), Math.max(1, totalPages));
}

function getCompactPaginationRange(page: number, totalPages: number): PaginationRangeItem[] {
	const total = Math.max(1, totalPages);
	const current = clampPage(page, total);

	if (total <= 3) {
		return Array.from({ length: total }, (_, index) => ({
			type: "page",
			page: index + 1,
		}));
	}

	if (current >= total - 1) {
		return [
			{ type: "ellipsis", key: "more" },
			...[total - 2, total - 1, total].map((pageNumber) => ({
				type: "page" as const,
				page: pageNumber,
			})),
		];
	}

	return [
		...(current <= 2 ? [1, 2, 3] : [current - 1, current, current + 1]).map((pageNumber) => ({
			type: "page" as const,
			page: pageNumber,
		})),
		{ type: "ellipsis", key: "more" },
	];
}

function getPaginationRange(
	page: number,
	totalPages: number,
	compact = false,
): PaginationRangeItem[] {
	const total = Math.max(1, totalPages);
	const current = clampPage(page, total);

	if (compact) return getCompactPaginationRange(current, total);

	if (total <= 7) {
		return Array.from({ length: total }, (_, index) => ({
			type: "page",
			page: index + 1,
		}));
	}

	const visiblePages = new Set([1, total, current, current - 1, current + 1]);
	if (current <= 4) {
		for (let pageNumber = 2; pageNumber <= 5; pageNumber += 1) {
			visiblePages.add(pageNumber);
		}
	}
	if (current >= total - 3) {
		for (let pageNumber = total - 4; pageNumber < total; pageNumber += 1) {
			visiblePages.add(pageNumber);
		}
	}

	const pages = Array.from(visiblePages)
		.filter((pageNumber) => pageNumber >= 1 && pageNumber <= total)
		.sort((left, right) => left - right);

	const items: PaginationRangeItem[] = [];
	let previousPage = 0;
	for (const pageNumber of pages) {
		if (previousPage > 0 && pageNumber - previousPage > 1) {
			items.push({ type: "ellipsis", key: `${previousPage}-${pageNumber}` });
		}
		items.push({ type: "page", page: pageNumber });
		previousPage = pageNumber;
	}

	return items;
}

export function PaginationControls({
	page,
	totalPages,
	onPageChange,
	className,
	compact,
	disabled,
}: PaginationControlsProps) {
	const total = Math.max(1, totalPages);
	const current = clampPage(page, total);
	const items = getPaginationRange(current, total, compact);

	const goToPage = (nextPage: number) => {
		if (disabled) return;
		const clampedPage = clampPage(nextPage, total);
		if (clampedPage === current) return;
		onPageChange(clampedPage);
	};

	return (
		<Pagination className={cn(className)}>
			<PaginationContent className={cn(compact && "gap-0.5")}>
				<PaginationItem>
					<PaginationPrevious
						text={compact ? "" : undefined}
						className={cn(
							compact && "size-7 gap-0 p-0 sm:pl-0 sm:pr-0 has-[>svg]:px-0 [&>span]:hidden",
						)}
						render={
							<button
								type="button"
								aria-label="Go to previous page"
								disabled={disabled || current <= 1}
								onClick={() => goToPage(current - 1)}
							/>
						}
					/>
				</PaginationItem>
				{items.map((item) =>
					item.type === "ellipsis" ? (
						<PaginationItem key={item.key}>
							<PaginationEllipsis className={cn(compact && "size-8")} />
						</PaginationItem>
					) : (
						<PaginationItem key={item.page}>
							<PaginationLink
								className={cn(compact && "size-7 text-xs")}
								isActive={item.page === current}
								aria-label={
									item.page === current
										? `Page ${item.page}, current page`
										: `Go to page ${item.page}`
								}
								render={
									<button
										type="button"
										aria-label={
											item.page === current
												? `Page ${item.page}, current page`
												: `Go to page ${item.page}`
										}
										disabled={disabled}
										onClick={() => goToPage(item.page)}
									/>
								}
							>
								{item.page}
							</PaginationLink>
						</PaginationItem>
					),
				)}
				<PaginationItem>
					<PaginationNext
						text={compact ? "" : undefined}
						className={cn(
							compact && "size-7 gap-0 p-0 sm:pl-0 sm:pr-0 has-[>svg]:px-0 [&>span]:hidden",
						)}
						render={
							<button
								type="button"
								aria-label="Go to next page"
								disabled={disabled || current >= total}
								onClick={() => goToPage(current + 1)}
							/>
						}
					/>
				</PaginationItem>
			</PaginationContent>
		</Pagination>
	);
}
