import { CircleNotchIcon as Loader2 } from "@phosphor-icons/react/dist/csr/CircleNotch";

import { cn } from "@/lib/utils";

interface SpinnerProps {
	className?: string;
	size?: number;
}

function Spinner({ className, size = 16 }: SpinnerProps) {
	return (
		<Loader2
			size={size}
			className={cn("animate-spin", className)}
			aria-hidden={false}
			aria-label="Loading"
		/>
	);
}

export { Spinner };
