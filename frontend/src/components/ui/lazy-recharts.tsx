import type * as React from "react";
import { createElement, forwardRef, useEffect, useState } from "react";

type RechartsModule = typeof import("recharts");
type RechartsComponent = React.ElementType<
	Record<string, unknown> & { ref?: React.ForwardedRef<unknown> }
>;

let rechartsModule: RechartsModule | null = null;
let rechartsModulePromise: Promise<RechartsModule> | null = null;

function loadRecharts() {
	rechartsModulePromise ??= import("recharts").then((module) => {
		rechartsModule = module;
		return module;
	});
	return rechartsModulePromise;
}

function rechartsComponent(name: keyof RechartsModule) {
	const Component = forwardRef<unknown, Record<string, unknown>>((props, ref) => {
		const [module, setModule] = useState<RechartsModule | null>(() => rechartsModule);

		useEffect(() => {
			if (module) return;
			let active = true;
			void loadRecharts().then((loadedModule) => {
				if (active) setModule(loadedModule);
			});
			return () => {
				active = false;
			};
		}, [module]);

		if (!module) return null;
		const LoadedComponent = module[name] as RechartsComponent;
		return createElement(LoadedComponent, { ...props, ref });
	});
	Component.displayName = `LazyRecharts.${String(name)}`;
	return Component;
}

export const Bar = rechartsComponent("Bar");
export const BarChart = rechartsComponent("BarChart");
export const CartesianGrid = rechartsComponent("CartesianGrid");
export const Label = rechartsComponent("Label");
export const Legend = rechartsComponent("Legend");
export const Pie = rechartsComponent("Pie");
export const PieChart = rechartsComponent("PieChart");
export const Rectangle = rechartsComponent("Rectangle");
export const ResponsiveContainer = rechartsComponent("ResponsiveContainer");
export const Sector = rechartsComponent("Sector");
export const Tooltip = rechartsComponent("Tooltip");
export const XAxis = rechartsComponent("XAxis");
export const YAxis = rechartsComponent("YAxis");
