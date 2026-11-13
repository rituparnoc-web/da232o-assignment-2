import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { logClientEvent, type ActionProposal, type LogContext, type TargetDescriptor } from "./api";

export interface ExecutionResult {
  status: "succeeded" | "failed" | "cancelled";
  target_id?: string;
  error_code?: string;
  message: string;
}

export type TableSide = "north" | "south" | "east" | "west";

interface HabitatTarget {
  id: string;
  label: string;
  category: "container" | "platform";
  color: string;
  root: THREE.Group;
  groundPosition: THREE.Vector3;
  status: "available" | "held" | "delivered";
  deliveredTo?: string;
}

const floorLimits = { minX: -6.3, maxX: 13.7, minZ: -4.6, maxZ: 4.6 };
const cellSize = 0.5;

function shadow(mesh: THREE.Mesh): THREE.Mesh {
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  return mesh;
}

function makeLabel(text: string, detail: string): THREE.Sprite {
  const canvas = document.createElement("canvas");
  canvas.width = 512;
  canvas.height = 112;
  const context = canvas.getContext("2d")!;
  context.fillStyle = "rgba(10, 28, 32, 0.92)";
  context.beginPath();
  context.roundRect(2, 2, 508, 108, 16);
  context.fill();
  context.fillStyle = "#d2f368";
  context.font = "500 23px 'DM Mono', monospace";
  context.fillText(detail.toUpperCase(), 24, 37);
  context.fillStyle = "#f3f5ec";
  context.font = "600 36px 'Space Grotesk', sans-serif";
  context.fillText(text, 24, 83);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, transparent: true, depthWrite: false }));
  sprite.scale.set(2.15, 0.47, 1);
  return sprite;
}

export class HabitatWorld {
  readonly scene: THREE.Scene;
  private readonly host: HTMLElement;
  private readonly renderer: THREE.WebGLRenderer;
  private readonly camera: THREE.PerspectiveCamera;
  private readonly controls: OrbitControls;
  private readonly robot = new THREE.Group();
  private readonly door = new THREE.Group();
  private readonly targets = new Map<string, HabitatTarget>();
  private readonly resizeObserver: ResizeObserver;
  private readonly obstacles = [
    { minX: -1.45, maxX: 1.45, minZ: -0.75, maxZ: 1.25 },
    { minX: 2.25, maxX: 3.45, minZ: 1.7, maxZ: 2.55 },
    { minX: 7.01, maxX: 7.29, minZ: -5.35, maxZ: -1.5 },
    { minX: 7.01, maxX: 7.29, minZ: 1.5, maxZ: 5.35 },
  ];
  private doorOpen = false;
  private carryId: string | null = null;
  private movementToken = 0;
  private frameId = 0;

  constructor(host: HTMLElement) {
    this.host = host;
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color("#10272b");
    this.scene.fog = new THREE.Fog("#10272b", 30, 75);
    this.camera = new THREE.PerspectiveCamera(42, 1, 0.1, 80);
    this.camera.position.set(10.5, 10.2, 12.8);
    this.renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true, alpha: false });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.2;
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.renderer.domElement.className = "world-canvas";
    host.replaceChildren(this.renderer.domElement);

    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.target.set(3.2, 0.25, -0.25);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.07;
    this.controls.minDistance = 8;
    this.controls.maxDistance = 60;
    this.controls.maxPolarAngle = Math.PI * 0.47;

    this.buildLighting();
    this.buildHabitat();
    this.buildTargets();
    this.buildRobot();
    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(host);
    this.resize();
    this.frameId = requestAnimationFrame(this.render);
  }

  private readonly render = (): void => {
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
    this.frameId = requestAnimationFrame(this.render);
  };

  private buildLighting(): void {
    this.scene.add(new THREE.HemisphereLight("#d9f4e3", "#14262a", 2.1));
    const key = new THREE.DirectionalLight("#ffe7bd", 3.1);
    key.position.set(-5, 11, 6);
    key.castShadow = true;
    key.shadow.mapSize.set(2048, 2048);
    key.shadow.camera.left = -12;
    key.shadow.camera.right = 12;
    key.shadow.camera.top = 12;
    key.shadow.camera.bottom = -12;
    key.shadow.bias = -0.00015;
    this.scene.add(key);
    const fill = new THREE.PointLight("#5ed8ca", 50, 20, 2);
    fill.position.set(5, 4, -3);
    this.scene.add(fill);
  }

  private buildHabitat(): void {
    const floor = shadow(new THREE.Mesh(
      new THREE.PlaneGeometry(21.75, 10.5),
      new THREE.MeshStandardMaterial({ color: "#20393c", roughness: 0.87, metalness: 0.08 }),
    ));
    floor.rotation.x = -Math.PI / 2;
    floor.position.set(3.625, -0.04, 0);
    this.scene.add(floor);

    const grid = new THREE.GridHelper(14, 28, "#5c7975", "#355153");
    grid.position.y = 0.015;
    const gridMaterial = grid.material as THREE.Material;
    gridMaterial.transparent = true;
    gridMaterial.opacity = 0.45;
    this.scene.add(grid);
    const secondGrid = new THREE.GridHelper(7, 14, "#5c7975", "#355153");
    secondGrid.position.set(10.75, 0.015, 0);
    const secondGridMaterial = secondGrid.material as THREE.Material;
    secondGridMaterial.transparent = true;
    secondGridMaterial.opacity = 0.45;
    this.scene.add(secondGrid);

    const wallMaterial = new THREE.MeshStandardMaterial({ color: "#294447", roughness: 0.82 });
    const backWall = shadow(new THREE.Mesh(new THREE.BoxGeometry(21.75, 2.6, 0.28), wallMaterial));
    backWall.position.set(3.625, 1.25, -5.35);
    this.scene.add(backWall);
    for (const x of [-7.15, 14.4]) {
      const side = shadow(new THREE.Mesh(new THREE.BoxGeometry(0.28, 2.6, 10.5), wallMaterial));
      side.position.set(x, 1.25, 0);
      this.scene.add(side);
    }
    for (const z of [-3.375, 3.375]) {
      const partition = shadow(new THREE.Mesh(new THREE.BoxGeometry(0.28, 2.6, 3.75), wallMaterial));
      partition.position.set(7.15, 1.25, z);
      this.scene.add(partition);
    }
    const doorPanel = shadow(new THREE.Mesh(
      new THREE.BoxGeometry(0.24, 2.4, 3),
      new THREE.MeshStandardMaterial({ color: "#78928a", roughness: 0.55, metalness: 0.35 }),
    ));
    doorPanel.position.set(0, 1.2, 1.5);
    this.door.position.set(7.15, 0, -1.5);
    this.door.add(doorPanel);
    const doorInsetMaterial = new THREE.MeshStandardMaterial({ color: "#314d4d", roughness: 0.62, metalness: 0.3 });
    for (const x of [-0.13, 0.13]) {
      const inset = new THREE.Mesh(new THREE.BoxGeometry(0.02, 1.65, 1.85), doorInsetMaterial);
      inset.position.set(x, 1.25, 1.5);
      this.door.add(inset);
      const handle = new THREE.Mesh(
        new THREE.BoxGeometry(0.07, 0.35, 0.06),
        new THREE.MeshStandardMaterial({ color: "#d2dfb8", metalness: 0.65, roughness: 0.35 }),
      );
      handle.position.set(x, 1.1, 2.65);
      this.door.add(handle);
    }
    this.scene.add(this.door);

    this.addZone("STORAGE", -3.4, -2.8, 5.2, 3.2, "#24504e");
    this.addZone("DELIVERY", 4.45, -2.8, 3.0, 3.2, "#3e5040");
    this.addZone("ROOM 2 / DELIVERY", 11.2, 2.8, 4.0, 3.2, "#3e5040");
    this.addBench();
    this.addWallMarkings();
    this.addRoomDetails();
    this.addWallStorage(5.1);
    this.addWallStorage(10.85);
  }

  private addWallStorage(x: number): void {
    const storage = new THREE.Group();
    const frameMaterial = new THREE.MeshStandardMaterial({ color: "#879e91", metalness: 0.55, roughness: 0.48 });
    const back = shadow(new THREE.Mesh(
      new THREE.BoxGeometry(1.3, 1.25, 0.12),
      new THREE.MeshStandardMaterial({ color: "#334e4e", roughness: 0.75 }),
    ));
    back.position.y = 1.3;
    storage.add(back);
    for (const height of [0.78, 1.38, 1.92]) {
      const shelf = shadow(new THREE.Mesh(new THREE.BoxGeometry(1.35, 0.08, 0.34), frameMaterial));
      shelf.position.set(0, height, 0.13);
      storage.add(shelf);
    }
    for (const [offset, height, color] of [
      [-0.38, 1.57, "#d8c780"], [0, 1.57, "#88bbb2"], [0.37, 1.57, "#d5a28b"],
      [-0.3, 0.97, "#9cb6ad"], [0.25, 0.97, "#c2d5a6"],
    ] as const) {
      const canister = shadow(new THREE.Mesh(
        new THREE.CylinderGeometry(0.12, 0.12, 0.3, 16),
        new THREE.MeshStandardMaterial({ color, roughness: 0.45, metalness: 0.25 }),
      ));
      canister.position.set(offset, height, 0.13);
      storage.add(canister);
      const cap = new THREE.Mesh(new THREE.CylinderGeometry(0.095, 0.095, 0.04, 16), frameMaterial);
      cap.position.set(offset, height + 0.17, 0.13);
      storage.add(cap);
    }
    storage.position.set(x, 0, -5.16);
    this.scene.add(storage);
  }

  private addRoomDetails(): void {
    const frameMaterial = new THREE.MeshStandardMaterial({ color: "#536d68", metalness: 0.38, roughness: 0.62 });
    const panelMaterial = new THREE.MeshStandardMaterial({ color: "#1c3437", metalness: 0.2, roughness: 0.7 });
    const lightMaterial = new THREE.MeshStandardMaterial({ color: "#c6e7c1", emissive: "#76c9a8", emissiveIntensity: 0.75 });
    for (const x of [-1.6, 2.5, 9.2, 12.5]) {
      const frame = new THREE.Mesh(new THREE.BoxGeometry(1.45, 1.05, 0.12), frameMaterial);
      frame.position.set(x, 1.25, -5.15);
      this.scene.add(frame);
      const panel = new THREE.Mesh(new THREE.BoxGeometry(1.25, 0.85, 0.04), panelMaterial);
      panel.position.set(x, 1.25, -5.06);
      this.scene.add(panel);
      for (let index = 0; index < 3; index += 1) {
        const vent = new THREE.Mesh(new THREE.BoxGeometry(0.72, 0.035, 0.025), frameMaterial);
        vent.position.set(x - 0.14, 1.02 + index * 0.14, -5.025);
        this.scene.add(vent);
      }
      const indicator = new THREE.Mesh(new THREE.BoxGeometry(0.09, 0.09, 0.03), lightMaterial);
      indicator.position.set(x + 0.48, 1.48, -5.02);
      this.scene.add(indicator);
    }
    for (const x of [-6.9, 0, 6.8, 8.3, 14.1]) {
      const rib = new THREE.Mesh(new THREE.BoxGeometry(0.09, 2.45, 0.12), frameMaterial);
      rib.position.set(x, 1.25, -5.13);
      this.scene.add(rib);
    }
    const thresholdMaterial = new THREE.MeshStandardMaterial({ color: "#d9b866", roughness: 0.82 });
    for (const z of [-1.2, -0.8, -0.4, 0, 0.4, 0.8, 1.2]) {
      const stripe = new THREE.Mesh(new THREE.BoxGeometry(0.35, 0.018, 0.1), thresholdMaterial);
      stripe.position.set(7.15, 0.03, z);
      this.scene.add(stripe);
    }
  }

  private addZone(label: string, x: number, z: number, width: number, depth: number, color: string): void {
    const patch = new THREE.Mesh(
      new THREE.PlaneGeometry(width, depth),
      new THREE.MeshStandardMaterial({ color, roughness: 1, transparent: true, opacity: 0.58 }),
    );
    patch.rotation.x = -Math.PI / 2;
    patch.position.set(x, 0.005, z);
    this.scene.add(patch);
    const points = [
      new THREE.Vector3(x - width / 2, 0.026, z - depth / 2),
      new THREE.Vector3(x + width / 2, 0.026, z - depth / 2),
      new THREE.Vector3(x + width / 2, 0.026, z + depth / 2),
      new THREE.Vector3(x - width / 2, 0.026, z + depth / 2),
      new THREE.Vector3(x - width / 2, 0.026, z - depth / 2),
    ];
    const line = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints(points),
      new THREE.LineBasicMaterial({ color: "#9bb2a4", transparent: true, opacity: 0.72 }),
    );
    this.scene.add(line);
    const text = makeLabel(label, "AREA");
    text.position.set(x, 0.52, z - depth / 2 + 0.3);
    text.scale.set(1.7, 0.37, 1);
    this.scene.add(text);
  }

  private addBench(): void {
    const bench = new THREE.Group();
    const top = shadow(new THREE.Mesh(
      new THREE.BoxGeometry(2.75, 0.34, 1.8),
      new THREE.MeshStandardMaterial({ color: "#41585a", roughness: 0.56, metalness: 0.22 }),
    ));
    top.position.y = 0.95;
    bench.add(top);
    const edgingMaterial = new THREE.MeshStandardMaterial({ color: "#9bafa2", roughness: 0.5, metalness: 0.5 });
    for (const z of [-0.84, 0.84]) {
      const edge = new THREE.Mesh(new THREE.BoxGeometry(2.65, 0.045, 0.045), edgingMaterial);
      edge.position.set(0, 1.13, z);
      bench.add(edge);
    }
    const consoleBase = shadow(new THREE.Mesh(
      new THREE.BoxGeometry(0.75, 0.09, 0.48),
      new THREE.MeshStandardMaterial({ color: "#718e85", roughness: 0.55, metalness: 0.35 }),
    ));
    consoleBase.position.set(-0.75, 1.165, -0.1);
    bench.add(consoleBase);
    const screen = shadow(new THREE.Mesh(
      new THREE.BoxGeometry(0.66, 0.43, 0.07),
      new THREE.MeshStandardMaterial({ color: "#18383b", roughness: 0.4, metalness: 0.25 }),
    ));
    screen.position.set(-0.75, 1.42, -0.28);
    bench.add(screen);
    const display = new THREE.Mesh(
      new THREE.BoxGeometry(0.54, 0.31, 0.015),
      new THREE.MeshStandardMaterial({ color: "#7cbeb3", emissive: "#285f5a", emissiveIntensity: 0.55 }),
    );
    display.position.set(-0.75, 1.43, -0.237);
    bench.add(display);
    const sample = shadow(new THREE.Mesh(
      new THREE.CylinderGeometry(0.15, 0.18, 0.37, 20),
      new THREE.MeshStandardMaterial({ color: "#c5d8b8", roughness: 0.42, metalness: 0.3 }),
    ));
    sample.position.set(0.08, 1.305, -0.22);
    bench.add(sample);
    const sampleCap = new THREE.Mesh(new THREE.CylinderGeometry(0.13, 0.13, 0.06, 20), edgingMaterial);
    sampleCap.position.set(0.08, 1.52, -0.22);
    bench.add(sampleCap);
    const toolCase = shadow(new THREE.Mesh(
      new THREE.BoxGeometry(0.62, 0.22, 0.4),
      new THREE.MeshStandardMaterial({ color: "#d4976d", roughness: 0.65, metalness: 0.12 }),
    ));
    toolCase.position.set(0.75, 1.23, 0.18);
    bench.add(toolCase);
    const latch = new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.06, 0.025), edgingMaterial);
    latch.position.set(0.75, 1.24, 0.39);
    bench.add(latch);
    for (const x of [-1.1, 1.1]) {
      for (const z of [-0.62, 0.62]) {
        const leg = shadow(new THREE.Mesh(
          new THREE.BoxGeometry(0.16, 0.95, 0.16),
          new THREE.MeshStandardMaterial({ color: "#83918a", metalness: 0.56, roughness: 0.4 }),
        ));
        leg.position.set(x, 0.45, z);
        bench.add(leg);
      }
    }
    bench.position.set(0, 0, 0.25);
    this.scene.add(bench);
    this.addCrateObstacle(2.85, 0, 2.15);
  }

  private addCrateObstacle(x: number, z: number, size: number): void {
    const crate = shadow(new THREE.Mesh(
      new THREE.BoxGeometry(size, 0.76, 0.86),
      new THREE.MeshStandardMaterial({ color: "#4d6260", roughness: 0.88 }),
    ));
    crate.position.set(x, 0.38, z);
    this.scene.add(crate);
    for (const offset of [-0.55, 0.55]) {
      const stripe = new THREE.Mesh(
        new THREE.BoxGeometry(0.09, 0.79, 0.88),
        new THREE.MeshStandardMaterial({ color: "#c5d28e", roughness: 0.7 }),
      );
      stripe.position.set(x + offset, 0.38, z);
      this.scene.add(stripe);
    }
  }

  private addWallMarkings(): void {
    const wallText = makeLabel("HABITAT 04", "LOW GRAVITY / STORAGE BAY");
    wallText.position.set(-3.85, 2.0, -5.16);
    wallText.scale.set(3.2, 0.7, 1);
    this.scene.add(wallText);
    for (let index = 0; index < 8; index += 1) {
      const rib = new THREE.Mesh(
        new THREE.BoxGeometry(0.045, 2.35, 0.08),
        new THREE.MeshStandardMaterial({ color: index % 2 ? "#506a66" : "#385453", roughness: 0.9 }),
      );
      rib.position.set(-6.3 + index * 0.25, 1.25, -5.16);
      this.scene.add(rib);
    }
  }

  private buildTargets(): void {
    this.addContainer("object_01", "Blue tote", "#2777de", "BLUE / CONTAINER", -4.45, -2.75);
    this.addContainer("object_02", "Red tote", "#e46855", "RED / CONTAINER", -2.75, -2.75);
    this.addContainer("object_03", "Yellow tote", "#e5bf49", "YELLOW / CONTAINER", -1.05, -2.75);
    this.addPlatform("delivery_01", 4.55, -2.75);
    this.addPlatform("delivery_02", 11.2, 2.75);
  }

  private addContainer(id: string, label: string, color: string, detail: string, x: number, z: number): void {
    const root = new THREE.Group();
    const bodyMaterial = new THREE.MeshStandardMaterial({ color, roughness: 0.44, metalness: 0.08 });
    const body = shadow(new THREE.Mesh(new THREE.BoxGeometry(1.08, 0.78, 0.88), bodyMaterial));
    body.position.y = 0.44;
    root.add(body);
    const lid = shadow(new THREE.Mesh(
      new THREE.BoxGeometry(1.14, 0.12, 0.94),
      new THREE.MeshStandardMaterial({ color: new THREE.Color(color).multiplyScalar(0.74), roughness: 0.5 }),
    ));
    lid.position.y = 0.87;
    root.add(lid);
    const seam = shadow(new THREE.Mesh(
      new THREE.BoxGeometry(0.055, 0.62, 0.03),
      new THREE.MeshStandardMaterial({ color: "#d7e3cf", roughness: 0.55 }),
    ));
    seam.position.set(0, 0.46, 0.453);
    root.add(seam);
    const labelSprite = makeLabel(id, detail);
    labelSprite.position.set(0, 1.43, 0.18);
    root.add(labelSprite);
    root.position.set(x, 0, z);
    this.scene.add(root);
    this.targets.set(id, {
      id,
      label,
      category: "container",
      color,
      root,
      groundPosition: new THREE.Vector3(x, 0, z),
      status: "available",
    });
  }

  private addPlatform(id: string, x: number, z: number): void {
    const root = new THREE.Group();
    const frameMaterial = new THREE.MeshStandardMaterial({ color: "#829482", roughness: 0.55, metalness: 0.48 });
    const base = shadow(new THREE.Mesh(new THREE.BoxGeometry(1.95, 0.32, 1.62), frameMaterial));
    base.position.y = 0.22;
    root.add(base);
    const pad = shadow(new THREE.Mesh(
      new THREE.BoxGeometry(1.64, 0.08, 1.32),
      new THREE.MeshStandardMaterial({ color: "#a5cf74", roughness: 0.66, emissive: "#243b12", emissiveIntensity: 0.2 }),
    ));
    pad.position.y = 0.43;
    root.add(pad);
    for (const [px, pz] of [[-0.8, -0.64], [0.8, -0.64], [-0.8, 0.64], [0.8, 0.64]]) {
      const post = shadow(new THREE.Mesh(new THREE.BoxGeometry(0.11, 0.42, 0.11), frameMaterial));
      post.position.set(px, 0.58, pz);
      root.add(post);
    }
    const trimMaterial = new THREE.MeshStandardMaterial({ color: "#d2dfb3", emissive: "#728b42", emissiveIntensity: 0.4 });
    for (const px of [-0.7, 0.7]) {
      const trim = new THREE.Mesh(new THREE.BoxGeometry(0.045, 0.015, 1.05), trimMaterial);
      trim.position.set(px, 0.478, 0);
      root.add(trim);
    }
    const lampMaterial = new THREE.MeshStandardMaterial({ color: "#d1f6b3", emissive: "#82c949", emissiveIntensity: 0.85 });
    for (const px of [-0.68, 0.68]) {
      const lamp = new THREE.Mesh(new THREE.BoxGeometry(0.16, 0.09, 0.025), lampMaterial);
      lamp.position.set(px, 0.24, 0.82);
      root.add(lamp);
    }
    const label = makeLabel(id, "DELIVERY / PLATFORM");
    label.position.set(0, 1.34, 0.12);
    root.add(label);
    root.position.set(x, 0, z);
    this.scene.add(root);
    this.targets.set(id, {
      id,
      label: id === "delivery_02" ? "Room 2 delivery platform" : "Delivery platform",
      category: "platform",
      color: "#a5cf74",
      root,
      groundPosition: new THREE.Vector3(x, 0, z),
      status: "available",
    });
  }

  private buildRobot(): void {
    const wheelMaterial = new THREE.MeshStandardMaterial({ color: "#111e20", roughness: 0.76, metalness: 0.2 });
    const hubMaterial = new THREE.MeshStandardMaterial({ color: "#b3c5b5", roughness: 0.42, metalness: 0.7 });
    for (const x of [-0.54, 0.54]) {
      for (const z of [-0.32, 0.32]) {
        const wheel = shadow(new THREE.Mesh(new THREE.CylinderGeometry(0.27, 0.27, 0.17, 24), wheelMaterial));
        wheel.rotation.z = Math.PI / 2;
        wheel.position.set(x, 0.3, z);
        this.robot.add(wheel);
        const hub = new THREE.Mesh(new THREE.CylinderGeometry(0.12, 0.12, 0.03, 20), hubMaterial);
        hub.rotation.z = Math.PI / 2;
        hub.position.set(x + Math.sign(x) * 0.09, 0.3, z);
        this.robot.add(hub);
      }
    }
    const chassis = shadow(new THREE.Mesh(
      new THREE.BoxGeometry(1.18, 0.55, 0.93),
      new THREE.MeshStandardMaterial({ color: "#3eb8a9", roughness: 0.38, metalness: 0.28 }),
    ));
    chassis.position.y = 0.72;
    this.robot.add(chassis);
    const bumper = shadow(new THREE.Mesh(
      new THREE.BoxGeometry(1.02, 0.13, 0.08),
      new THREE.MeshStandardMaterial({ color: "#c7d7c6", metalness: 0.55, roughness: 0.4 }),
    ));
    bumper.position.set(0, 0.55, 0.49);
    this.robot.add(bumper);
    const headlightMaterial = new THREE.MeshStandardMaterial({ color: "#f6e8aa", emissive: "#e4b85e", emissiveIntensity: 0.8 });
    for (const x of [-0.38, 0.38]) {
      const headlight = new THREE.Mesh(new THREE.BoxGeometry(0.16, 0.09, 0.025), headlightMaterial);
      headlight.position.set(x, 0.79, 0.48);
      this.robot.add(headlight);
    }
    const top = shadow(new THREE.Mesh(
      new THREE.BoxGeometry(0.83, 0.2, 0.65),
      new THREE.MeshStandardMaterial({ color: "#d9dfc5", roughness: 0.38, metalness: 0.22 }),
    ));
    top.position.set(0, 1.07, -0.03);
    this.robot.add(top);
    for (const x of [-0.23, -0.12, -0.01]) {
      const vent = new THREE.Mesh(
        new THREE.BoxGeometry(0.055, 0.012, 0.2),
        new THREE.MeshStandardMaterial({ color: "#637e74", roughness: 0.65 }),
      );
      vent.position.set(x, 1.175, -0.18);
      this.robot.add(vent);
    }
    const head = shadow(new THREE.Mesh(
      new THREE.CylinderGeometry(0.27, 0.34, 0.31, 24),
      new THREE.MeshStandardMaterial({ color: "#f2eee0", roughness: 0.32, metalness: 0.25 }),
    ));
    head.position.set(0, 1.31, 0.08);
    this.robot.add(head);
    const eye = new THREE.Mesh(
      new THREE.SphereGeometry(0.09, 20, 16),
      new THREE.MeshStandardMaterial({ color: "#b3f05c", emissive: "#7dca23", emissiveIntensity: 1.7, roughness: 0.22 }),
    );
    eye.position.set(0, 1.31, 0.347);
    this.robot.add(eye);
    const antenna = shadow(new THREE.Mesh(
      new THREE.CylinderGeometry(0.024, 0.024, 0.36, 8),
      new THREE.MeshStandardMaterial({ color: "#b4c5b4", metalness: 0.55, roughness: 0.38 }),
    ));
    antenna.position.set(0.16, 1.62, -0.08);
    this.robot.add(antenna);
    const antennaTip = new THREE.Mesh(
      new THREE.SphereGeometry(0.07, 16, 12),
      new THREE.MeshStandardMaterial({ color: "#f27855", emissive: "#b83a20", emissiveIntensity: 0.45 }),
    );
    antennaTip.position.set(0.16, 1.82, -0.08);
    this.robot.add(antennaTip);
    const label = makeLabel("M-04", "ROVER / ACTIVE");
    label.position.set(0, 2.15, 0);
    label.scale.set(1.45, 0.32, 1);
    this.robot.add(label);
    this.robot.position.set(-5.25, 0, 3.55);
    this.scene.add(this.robot);
  }

  private resize(): void {
    const width = Math.max(1, this.host.clientWidth);
    const height = Math.max(1, this.host.clientHeight);
    const aspect = width / height;
    this.camera.aspect = aspect;
    this.camera.updateProjectionMatrix();
    const direction = this.camera.position.clone().sub(this.controls.target).normalize();
    this.camera.position.copy(this.controls.target).addScaledVector(direction, aspect < 1 ? 38 / aspect : 25);
    this.renderer.setSize(width, height, false);
  }

  getVisibleTargets(): TargetDescriptor[] {
    return [...this.targets.values()]
      .filter((target) => target.status !== "delivered")
      .map((target) => ({
        target_id: target.id,
        category: target.category,
        in_interaction_range: this.robot.position.distanceTo(target.groundPosition)
          <= (target.category === "platform" ? 1.95 : 1.65),
      }));
  }

  getHeldObjectId(): string | null {
    return this.carryId;
  }

  getAgentCoordinates(): { x: number; z: number } {
    return { x: this.robot.position.x, z: this.robot.position.z };
  }

  captureJpeg(): string {
    this.renderer.render(this.scene, this.camera);
    return this.renderer.domElement.toDataURL("image/jpeg", 0.78).split(",", 2)[1] ?? "";
  }

  isDelivered(id: string, platformId?: string): boolean {
    const target = this.targets.get(id);
    return target?.status === "delivered" && (!platformId || target.deliveredTo === platformId);
  }

  stopMovement(): void {
    this.movementToken += 1;
  }

  async execute(action: ActionProposal, context: LogContext = {}): Promise<ExecutionResult> {
    switch (action.action) {
      case "navigate_to":
        return this.navigateTo(action.target_id ?? "", undefined, context);
      case "pick_up":
        return this.pickUp(action.target_id ?? "", context);
      case "place_on":
        return this.placeOn(action.target_id ?? "", context);
      case "stop":
        this.stopMovement();
        return { status: "cancelled", message: "Rover stopped." };
      case "finish":
        return { status: "succeeded", message: "VLM requested task verification." };
    }
  }

  async executePickAndPlace(targetId: string, onPhase: (phase: string) => void, tableSide?: TableSide, platformId = "delivery_01", context: LogContext = {}): Promise<ExecutionResult> {
    const target = this.targets.get(targetId);
    if (!target || target.category !== "container" || target.status === "delivered") {
      return { status: "failed", target_id: targetId, error_code: "unknown_target", message: "Selected container is not available." };
    }
    if (this.carryId && this.carryId !== targetId) {
      return { status: "failed", target_id: targetId, error_code: "already_holding", message: "Rover is carrying a different container." };
    }

    if (this.carryId !== targetId) {
      if (this.robot.position.distanceTo(target.groundPosition) > 1.65) {
        onPhase(`Approaching ${target.label}`);
        const approach = await this.navigateTo(targetId, undefined, context);
        if (approach.status !== "succeeded") return approach;
      }
      onPhase(`Picking up ${target.label}`);
      const pickup = await this.pickUp(targetId, context);
      if (pickup.status !== "succeeded") return pickup;
    }

    if (tableSide) {
      onPhase(`Going around the ${tableSide} side of the table`);
      const route = await this.goAroundTable(tableSide, context);
      if (route.status !== "succeeded") return route;
    }

    onPhase("Approaching delivery platform");
    const deliveryApproach = await this.navigateTo(platformId, onPhase, context);
    if (deliveryApproach.status !== "succeeded") return deliveryApproach;

    onPhase("Placing container on delivery platform");
    return this.placeOn(platformId, context);
  }

  async goAroundTable(side: TableSide, context: LogContext = {}): Promise<ExecutionResult> {
    logClientEvent("rover.table_route", { side }, context);
    let waypoints: THREE.Vector3[];
    if (side === "north" || side === "south") {
      const z = side === "north" ? -1.8 : 3.3;
      waypoints = [new THREE.Vector3(-2.3, 0, z), new THREE.Vector3(2.3, 0, z)];
    } else {
      const x = side === "west" ? -2.3 : 4.3;
      waypoints = [new THREE.Vector3(x, 0, -1.8), new THREE.Vector3(x, 0, 3.3)];
      if (this.robot.position.z > 0.75) waypoints.reverse();
    }
    for (const waypoint of waypoints) {
      const result = await this.walkPath(waypoint, context);
      if (result.status !== "succeeded") return result;
    }
    return { status: "succeeded", message: `Rover passed the ${side} side of the table.` };
  }

  private async navigateTo(id: string, onPhase?: (phase: string) => void, context: LogContext = {}): Promise<ExecutionResult> {
    logClientEvent("rover.navigate", { target_id: id }, context);
    const target = this.targets.get(id);
    if (!target || target.status === "delivered") {
      return { status: "failed", target_id: id, error_code: "unknown_target", message: "Target is not available." };
    }
    if (!this.doorOpen && target.groundPosition.x > 7.15) {
      onPhase?.("Approaching room 2 door");
      const approach = await this.walkPath(new THREE.Vector3(6, 0, 0), context);
      if (approach.status !== "succeeded") return approach;
      onPhase?.("Opening room 2 door");
      logClientEvent("rover.door_opening", { target_id: id }, context);
      const token = ++this.movementToken;
      const opened = await new Promise<boolean>((resolve) => {
        const start = performance.now();
        const step = (now: number) => {
          if (token !== this.movementToken) {
            this.door.rotation.y = 0;
            resolve(false);
            return;
          }
          const progress = Math.min(1, (now - start) / 800);
          this.door.rotation.y = progress * Math.PI / 2;
          if (progress === 1) resolve(true);
          else requestAnimationFrame(step);
        };
        requestAnimationFrame(step);
      });
      if (!opened) {
        logClientEvent("rover.door_cancelled", {}, context);
        return { status: "cancelled", error_code: "cancelled", message: "Door opening cancelled." };
      }
      this.doorOpen = true;
      logClientEvent("rover.door_opened", {}, context);
    }
    const away = this.robot.position.clone().sub(target.groundPosition).setY(0);
    if (away.lengthSq() < 0.01) away.set(0, 0, 1);
    away.normalize().multiplyScalar(target.category === "platform" ? 1.45 : 1.18);
    const destination = target.groundPosition.clone().add(away);
    const result = await this.walkPath(destination, context);
    if (result.status === "succeeded") return { ...result, target_id: id, message: `Rover reached ${target.label}.` };
    return { ...result, target_id: id };
  }

  private async pickUp(id: string, context: LogContext): Promise<ExecutionResult> {
    if (this.carryId) {
      return { status: "failed", target_id: id, error_code: "already_holding", message: "Rover is already carrying an item." };
    }
    const target = this.targets.get(id);
    if (!target || target.category !== "container" || target.status !== "available") {
      return { status: "failed", target_id: id, error_code: "unknown_target", message: "That container is not available." };
    }
    if (this.robot.position.distanceTo(target.groundPosition) > 1.65) {
      return { status: "failed", target_id: id, error_code: "out_of_range", message: "Container is outside pickup range. Navigate closer first." };
    }
    target.status = "held";
    this.carryId = id;
    this.robot.add(target.root);
    target.root.position.set(0, 1.58, 0.82);
    target.root.rotation.set(0, 0, 0);
    logClientEvent("rover.picked_up", { target_id: id, ...this.getAgentCoordinates() }, context);
    return { status: "succeeded", target_id: id, message: `Picked up ${target.label}.` };
  }

  private async placeOn(id: string, context: LogContext): Promise<ExecutionResult> {
    if (!this.carryId) {
      return { status: "failed", target_id: id, error_code: "nothing_held", message: "Rover is not carrying a container." };
    }
    const platform = this.targets.get(id);
    if (!platform || platform.category !== "platform") {
      return { status: "failed", target_id: id, error_code: "unknown_target", message: "Placement target is not a platform." };
    }
    if (this.robot.position.distanceTo(platform.groundPosition) > 1.95) {
      return { status: "failed", target_id: id, error_code: "out_of_range", message: "Platform is outside placement range. Navigate closer first." };
    }
    const carried = this.targets.get(this.carryId)!;
    this.robot.remove(carried.root);
    this.scene.add(carried.root);
    carried.root.position.copy(platform.groundPosition);
    carried.root.position.y = 0.52;
    carried.root.rotation.set(0, 0, 0);
    carried.status = "delivered";
    carried.deliveredTo = id;
    const placedId = this.carryId;
    this.carryId = null;
    logClientEvent("rover.placed", { target_id: placedId, platform_id: id, ...this.getAgentCoordinates() }, context);
    return { status: "succeeded", target_id: id, message: `Placed ${carried.label} on ${platform.label} (${placedId}).` };
  }

  private async walkPath(destination: THREE.Vector3, context: LogContext): Promise<ExecutionResult> {
    const path = this.findPath(this.robot.position, destination);
    if (!path) {
      logClientEvent("rover.unreachable", { destination_x: destination.x, destination_z: destination.z }, context);
      return { status: "failed", error_code: "unreachable_target", message: "No safe path found." };
    }
    const token = ++this.movementToken;
    logClientEvent("rover.path_started", {
      ...this.getAgentCoordinates(), destination_x: destination.x, destination_z: destination.z,
      waypoints: path.length, movement_token: token,
    }, context);
    for (const [index, point] of path.entries()) {
      const reached = await this.walkSegment(point, token);
      if (!reached) {
        logClientEvent("rover.movement_cancelled", { ...this.getAgentCoordinates(), movement_token: token }, context);
        return { status: "cancelled", error_code: "cancelled", message: "Movement cancelled." };
      }
      logClientEvent("rover.waypoint_reached", {
        waypoint: index + 1, total: path.length, ...this.getAgentCoordinates(), movement_token: token,
      }, context);
    }
    logClientEvent("rover.path_completed", { ...this.getAgentCoordinates(), movement_token: token }, context);
    return { status: "succeeded", message: "Rover reached its destination." };
  }

  private findPath(start: THREE.Vector3, destination: THREE.Vector3): THREE.Vector3[] | null {
    const columns = Math.round((floorLimits.maxX - floorLimits.minX) / cellSize) + 1;
    const rows = Math.round((floorLimits.maxZ - floorLimits.minZ) / cellSize) + 1;
    const toCell = (point: THREE.Vector3): [number, number] => [
      Math.max(0, Math.min(columns - 1, Math.round((point.x - floorLimits.minX) / cellSize))),
      Math.max(0, Math.min(rows - 1, Math.round((point.z - floorLimits.minZ) / cellSize))),
    ];
    const [sx, sz] = toCell(start);
    const [gx, gz] = toCell(destination);
    const key = (x: number, z: number) => `${x},${z}`;
    const queue: Array<[number, number]> = [[sx, sz]];
    const previous = new Map<string, string | null>([[key(sx, sz), null]]);
    const directions: Array<[number, number]> = [[1, 0], [-1, 0], [0, 1], [0, -1]];
    let found = false;

    while (queue.length) {
      const [x, z] = queue.shift()!;
      if (x === gx && z === gz) { found = true; break; }
      for (const [dx, dz] of directions) {
        const nx = x + dx;
        const nz = z + dz;
        const nextKey = key(nx, nz);
        if (nx < 0 || nx >= columns || nz < 0 || nz >= rows || previous.has(nextKey)) continue;
        const worldX = floorLimits.minX + nx * cellSize;
        const worldZ = floorLimits.minZ + nz * cellSize;
        const blocked = this.obstacles.some((obstacle) =>
          worldX > obstacle.minX - 0.38 && worldX < obstacle.maxX + 0.38
          && worldZ > obstacle.minZ - 0.38 && worldZ < obstacle.maxZ + 0.38,
        ) || (!this.doorOpen && worldX > 6.63 && worldX < 7.67 && worldZ > -1.88 && worldZ < 1.88)
          || (this.doorOpen && worldX > 6.77 && worldX < 10.53 && worldZ > -2 && worldZ < -1);
        if (blocked) continue;
        previous.set(nextKey, key(x, z));
        queue.push([nx, nz]);
      }
    }

    if (!found) return null;
    const path: THREE.Vector3[] = [];
    let cursor: string | null = key(gx, gz);
    while (cursor && cursor !== key(sx, sz)) {
      const [x, z] = cursor.split(",").map(Number);
      path.push(new THREE.Vector3(floorLimits.minX + x * cellSize, 0, floorLimits.minZ + z * cellSize));
      cursor = previous.get(cursor) ?? null;
    }
    path.reverse();
    path.push(new THREE.Vector3(destination.x, 0, destination.z));
    return path;
  }

  private walkSegment(destination: THREE.Vector3, token: number): Promise<boolean> {
    const start = this.robot.position.clone();
    const distance = start.distanceTo(destination);
    if (distance < 0.015) return Promise.resolve(true);
    this.robot.lookAt(destination.x, this.robot.position.y, destination.z);
    const duration = Math.max(90, distance / 2.3 * 1000);
    const begin = performance.now();
    return new Promise((resolve) => {
      const step = (now: number) => {
        if (token !== this.movementToken) { resolve(false); return; }
        const progress = Math.min(1, (now - begin) / duration);
        const eased = progress * progress * (3 - 2 * progress);
        this.robot.position.lerpVectors(start, destination, eased);
        if (progress >= 1) resolve(true);
        else requestAnimationFrame(step);
      };
      requestAnimationFrame(step);
    });
  }

  dispose(): void {
    cancelAnimationFrame(this.frameId);
    this.stopMovement();
    this.resizeObserver.disconnect();
    this.controls.dispose();
    this.renderer.dispose();
  }
}