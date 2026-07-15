declare module 'd3-force' {
  export interface SimulationNode {
    id: string;
    x?: number;
    y?: number;
    vx?: number;
    vy?: number;
    radius?: number;
  }

  export interface SimulationLink {
    source: string | SimulationNode;
    target: string | SimulationNode;
  }

  export interface Simulation {
    (nodes: SimulationNode[]): Simulation;
    force(name: string, force?: any): Simulation;
    alpha(value?: number): number | Simulation;
    alphaDecay(value?: number): number | Simulation;
    alphaMin(value?: number): number | Simulation;
    alphaTarget(value?: number): number | Simulation;
    velocityDecay(value?: number): number | Simulation;
    restart(): Simulation;
    stop(): Simulation;
    tick(iterations?: number): Simulation;
    find(x: number, y: number, radius?: number): SimulationNode | undefined;
    on(type: 'tick' | 'end', callback: () => void): Simulation;
  }

  export function forceSimulation(nodes?: SimulationNode[]): Simulation;

  export function forceManyBody(): {
    strength(strength?: number | ((node: SimulationNode) => number)): any;
    distanceMax(distance?: number): any;
    distanceMin(distance?: number): any;
    theta(theta?: number): any;
  };

  export function forceLink(links?: SimulationLink[]): {
    id(id: (node: SimulationNode) => string): any;
    distance(distance?: number | ((link: SimulationLink) => number)): any;
    strength(strength?: number | ((link: SimulationLink) => number)): any;
    iterations(iterations?: number): any;
  };

  export function forceCenter(x: number, y: number): {
    x(x?: number): number | any;
    y(y?: number): number | any;
    strength(strength?: number): number | any;
  };

  export function forceCollide(): {
    radius(radius?: number | ((node: SimulationNode) => number)): any;
    strength(strength?: number | ((node: SimulationNode) => number)): any;
    iterations(iterations?: number): any;
  };

  export function forceX(x?: number): {
    x(x?: number | ((node: SimulationNode) => number)): number | any;
    strength(strength?: number | ((node: SimulationNode) => number)): number | any;
  };

  export function forceY(y?: number): {
    y(y?: number | ((node: SimulationNode) => number)): number | any;
    strength(strength?: number | ((node: SimulationNode) => number)): number | any;
  };
}
