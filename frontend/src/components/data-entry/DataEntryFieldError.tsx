import { WarningCircleIcon as AlertCircle } from "@phosphor-icons/react/dist/csr/WarningCircle";
import type { ReactNode } from "react";

export function DataEntryFieldError({ id, children }: { id?: string; children?: ReactNode }) {
	if (!children) return null;
	return (
		<p id={id} className="flex items-center gap-1 text-sm text-destructive">
			<AlertCircle className="size-3.5 shrink-0" aria-hidden />
			<span>{children}</span>
		</p>
	);
}
