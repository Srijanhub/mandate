import React, { useRef } from 'react';
import { Environment, Float, Lightformer } from '@react-three/drei';
import { Canvas, useFrame } from '@react-three/fiber';
import * as THREE from 'three';

interface PhotonKnotSceneProps {
  theme: 'dark' | 'light';
  reducedMotion: boolean;
  interactive?: boolean;
  scale?: number;
}

const KnotSculpture: React.FC<{
  theme: 'dark' | 'light';
  reducedMotion: boolean;
  interactive: boolean;
  scale: number;
}> = ({ theme, reducedMotion, interactive, scale }) => {
  const rootRef = useRef<THREE.Group>(null);
  const outerRingRef = useRef<THREE.Mesh>(null);
  const innerRingRef = useRef<THREE.Mesh>(null);

  const isDark = theme === 'dark';
  const brassColor = isDark ? '#B69A70' : '#92764F';
  const titaniumColor = isDark ? '#A9B0B9' : '#59636E';
  const glassColor = isDark ? '#DCE2EB' : '#F4F3EF';

  useFrame((state, delta) => {
    if (!rootRef.current) return;
    if (!reducedMotion) {
      rootRef.current.rotation.y += delta * 0.16;
      rootRef.current.rotation.x = THREE.MathUtils.lerp(
        rootRef.current.rotation.x,
        interactive ? state.pointer.y * 0.28 + 0.14 : 0.14,
        0.04,
      );
      rootRef.current.rotation.z = THREE.MathUtils.lerp(
        rootRef.current.rotation.z,
        interactive ? -state.pointer.x * 0.22 : 0,
        0.04,
      );
      if (outerRingRef.current) {
        outerRingRef.current.rotation.z -= delta * 0.12;
      }
      if (innerRingRef.current) {
        innerRingRef.current.rotation.y += delta * 0.2;
      }
    }
  });

  const content = (
    <group ref={rootRef} scale={scale}>
      {/* Outer Optical Refractive Glass Knot */}
      <mesh castShadow receiveShadow>
        <torusKnotGeometry args={[1.05, 0.24, 180, 32, 2, 3]} />
        <meshPhysicalMaterial
          color={glassColor}
          transmission={0.86}
          opacity={1}
          transparent
          roughness={0.07}
          metalness={0.05}
          ior={1.52}
          thickness={1.25}
          attenuationDistance={2.2}
          attenuationColor={isDark ? '#A9B0B9' : '#D0D2D1'}
          clearcoat={1}
          clearcoatRoughness={0.06}
          reflectivity={0.92}
        />
      </mesh>

      {/* Internal Machined Titanium Harmonic Filament */}
      <mesh>
        <torusKnotGeometry args={[1.05, 0.068, 160, 18, 2, 3]} />
        <meshStandardMaterial
          color={titaniumColor}
          metalness={0.95}
          roughness={0.18}
        />
      </mesh>

      {/* Recessed Brass / Bronze Precision Core Node */}
      <mesh>
        <icosahedronGeometry args={[0.22, 1]} />
        <meshStandardMaterial color={brassColor} metalness={0.92} roughness={0.22} />
      </mesh>

      {/* Primary Brass Calibrated Datum Ring */}
      <mesh ref={outerRingRef} rotation={[Math.PI / 2.6, 0.35, 0]}>
        <torusGeometry args={[1.76, 0.016, 16, 128]} />
        <meshStandardMaterial color={brassColor} metalness={0.9} roughness={0.24} />
      </mesh>

      {/* Secondary Titanium Orthogonal Ring */}
      <mesh ref={innerRingRef} rotation={[-Math.PI / 3.1, -0.4, 0.2]}>
        <torusGeometry args={[1.52, 0.01, 12, 108]} />
        <meshStandardMaterial color={titaniumColor} metalness={0.88} roughness={0.28} />
      </mesh>
    </group>
  );

  if (reducedMotion) return content;

  return (
    <Float speed={1.35} rotationIntensity={0.08} floatIntensity={0.28}>
      {content}
    </Float>
  );
};

const PhotonKnotCanvas: React.FC<PhotonKnotSceneProps> = ({
  theme,
  reducedMotion,
  interactive = true,
  scale = 1,
}) => {
  const isDark = theme === 'dark';

  return (
    <Canvas
      dpr={[1, 2]}
      camera={{ position: [0, 0, 5.2], fov: 38 }}
      gl={{
        antialias: true,
        alpha: true,
        powerPreference: 'high-performance',
        toneMapping: THREE.ACESFilmicToneMapping,
        toneMappingExposure: isDark ? 1.1 : 1.02,
      }}
      style={{ width: '100%', height: '100%', display: 'block' }}
    >
      <ambientLight intensity={isDark ? 0.35 : 0.65} />
      <directionalLight
        position={[4.5, 5.5, 4]}
        intensity={isDark ? 1.85 : 1.5}
        color={isDark ? '#F5EFE6' : '#FFFFFF'}
      />
      <directionalLight
        position={[-4.5, -3.5, -3]}
        intensity={isDark ? 1.15 : 0.85}
        color={isDark ? '#B69A70' : '#92764F'}
      />
      <pointLight
        position={[0, 2.5, 3]}
        intensity={isDark ? 1.4 : 0.9}
        color={isDark ? '#A9B0B9' : '#59636E'}
      />

      <Environment resolution={256}>
        <group rotation={[-Math.PI / 4, 0, 0]}>
          <Lightformer
            form="rect"
            intensity={isDark ? 2.4 : 2.1}
            color="#FFFFFF"
            position={[0, 4, -2]}
            scale={[10, 3, 1]}
          />
          <Lightformer
            form="rect"
            intensity={1.5}
            color={isDark ? '#B69A70' : '#92764F'}
            position={[4, -2, 2]}
            scale={[6, 2, 1]}
          />
          <Lightformer
            form="circle"
            intensity={1.3}
            color={isDark ? '#A9B0B9' : '#D0D2D1'}
            position={[-4, 1, 2]}
            scale={3.5}
          />
        </group>
      </Environment>

      <KnotSculpture
        theme={theme}
        reducedMotion={reducedMotion}
        interactive={interactive}
        scale={scale}
      />
    </Canvas>
  );
};

export default PhotonKnotCanvas;
