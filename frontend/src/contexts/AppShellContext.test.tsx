import { render, screen } from "@testing-library/react";
import { StrictMode } from "react";
import { describe, expect, it } from "vitest";
import {
	AppShellProvider,
	useAppShellHeader,
	useAppShellHeaderRegistration,
} from "./AppShellContext";

function Header() {
	const { title } = useAppShellHeader();
	return <h1>{title}</h1>;
}

function Page({ title }: { title: string }) {
	useAppShellHeaderRegistration(title);
	return null;
}

function Shell({ first, second }: { first: boolean; second: boolean }) {
	return (
		<StrictMode>
			<AppShellProvider>
				<Header />
				{first ? <Page title="First page" /> : null}
				{second ? <Page title="Second page" /> : null}
			</AppShellProvider>
		</StrictMode>
	);
}

describe("AppShellProvider header cleanup", () => {
	it("preserves the current registration when an older page unmounts", () => {
		const { rerender } = render(<Shell first second />);
		expect(screen.getByRole("heading").textContent).toBe("Second page");
		rerender(<Shell first={false} second />);
		expect(screen.getByRole("heading").textContent).toBe("Second page");
	});

	it("restores the default header after the current page unmounts in Strict Mode", () => {
		const { rerender } = render(<Shell first second={false} />);
		expect(screen.getByRole("heading").textContent).toBe("First page");
		rerender(<Shell first={false} second={false} />);
		expect(screen.getByRole("heading").textContent).toBe("Accord");
	});
});
