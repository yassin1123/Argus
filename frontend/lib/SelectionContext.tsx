"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";

type SelectionState = {
  selectedClaimId: string | null;
  hoveredClaimId: string | null;
  selectedStage: string | null;
  setSelectedClaim: (id: string | null) => void;
  setHoveredClaim: (id: string | null) => void;
  setSelectedStage: (stage: string | null) => void;
  toggleClaim: (id: string) => void;
};

const SelectionContext = createContext<SelectionState | null>(null);

export function SelectionProvider({ children }: { children: ReactNode }) {
  const [selectedClaimId, setSelectedClaimIdState] = useState<string | null>(null);
  const [hoveredClaimId, setHoveredClaimIdState] = useState<string | null>(null);
  const [selectedStage, setSelectedStageState] = useState<string | null>(null);

  const setSelectedClaim = useCallback((id: string | null) => {
    setSelectedClaimIdState(id);
  }, []);

  const setHoveredClaim = useCallback((id: string | null) => {
    setHoveredClaimIdState(id);
  }, []);

  const setSelectedStage = useCallback((stage: string | null) => {
    setSelectedStageState(stage);
  }, []);

  const toggleClaim = useCallback((id: string) => {
    setSelectedClaimIdState((prev) => (prev === id ? null : id));
  }, []);

  const value = useMemo<SelectionState>(
    () => ({
      selectedClaimId,
      hoveredClaimId,
      selectedStage,
      setSelectedClaim,
      setHoveredClaim,
      setSelectedStage,
      toggleClaim,
    }),
    [
      selectedClaimId,
      hoveredClaimId,
      selectedStage,
      setSelectedClaim,
      setHoveredClaim,
      setSelectedStage,
      toggleClaim,
    ]
  );

  return <SelectionContext.Provider value={value}>{children}</SelectionContext.Provider>;
}

export function useSelection(): SelectionState {
  const ctx = useContext(SelectionContext);
  if (!ctx) {
    // Graceful no-op fallback so components can be used outside the provider.
    return {
      selectedClaimId: null,
      hoveredClaimId: null,
      selectedStage: null,
      setSelectedClaim: () => {},
      setHoveredClaim: () => {},
      setSelectedStage: () => {},
      toggleClaim: () => {},
    };
  }
  return ctx;
}

/** True if this claim id is currently selected OR hovered — used for visual highlight. */
export function useClaimHighlight(claimId: string): {
  isSelected: boolean;
  isHovered: boolean;
  isActive: boolean;
} {
  const { selectedClaimId, hoveredClaimId } = useSelection();
  const isSelected = selectedClaimId === claimId;
  const isHovered = hoveredClaimId === claimId;
  return { isSelected, isHovered, isActive: isSelected || isHovered };
}
