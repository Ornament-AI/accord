export class ApiError extends Error {
	public readonly status: number;
	public readonly detail: string;
	public readonly code?: string;

	constructor(message: string, status: number, options?: { detail?: string; code?: string }) {
		super(message);
		this.name = "ApiError";
		this.status = status;
		this.detail = options?.detail ?? message;
		this.code = options?.code;
	}
}

type MaybeMessage = {
	message?: unknown;
};

export function getErrorMessage(error: unknown, fallback = "Something went wrong."): string {
	if (error instanceof Error) {
		return error.message;
	}

	if (typeof error === "string" && error.length > 0) {
		return error;
	}

	if (error && typeof error === "object") {
		const maybeMessage = (error as MaybeMessage).message;
		if (typeof maybeMessage === "string" && maybeMessage.length > 0) {
			return maybeMessage;
		}
	}

	return fallback;
}
