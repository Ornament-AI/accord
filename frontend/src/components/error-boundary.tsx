import { Component, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { getErrorMessage } from "@/lib/errors";

interface ErrorBoundaryProps {
	children: ReactNode;
	fallback?: ReactNode;
}

interface ErrorBoundaryState {
	hasError: boolean;
	error: Error | null;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
	constructor(props: ErrorBoundaryProps) {
		super(props);
		this.state = { hasError: false, error: null };
	}

	static getDerivedStateFromError(error: Error): ErrorBoundaryState {
		return { hasError: true, error };
	}

	componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
		console.error("Error caught by boundary", error, errorInfo.componentStack);
	}

	override render() {
		if (this.state.hasError) {
			if (this.props.fallback) {
				return this.props.fallback;
			}

			return (
				<div className="flex h-screen items-center justify-center p-4">
					<div className="text-center max-w-md" role="alert">
						<h1 className="text-2xl font-bold mb-2">Something Went Wrong</h1>
						<p className="text-muted-foreground mb-4">
							{getErrorMessage(this.state.error, "An unexpected error occurred")}
						</p>
						<div className="flex gap-2 justify-center">
							<Button
								variant="default"
								onClick={() => {
									this.setState({ hasError: false, error: null });
								}}
							>
								Try Again
							</Button>
							<Button
								variant="outline"
								onClick={() => {
									window.location.reload();
								}}
							>
								Reload Page
							</Button>
						</div>
					</div>
				</div>
			);
		}

		return this.props.children;
	}
}
