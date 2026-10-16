package com.wynndle.panorama.mixin;

import net.minecraft.client.DeltaTracker;
import net.minecraft.client.Minecraft;
import net.minecraft.client.renderer.GameRenderer;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Redirect;

// Each face of the panorama is drawn twice and the second kept: Distant
// Horizons is one frame late after the camera turns, so the first face came
// out without the far landscape or the clouds.
@Mixin(Minecraft.class)
public class PanoramaWarmupMixin {
	@Redirect(method = "grabPanoramixScreenshot",
		at = @At(value = "INVOKE", target = "Lnet/minecraft/client/renderer/GameRenderer;renderLevel(Lnet/minecraft/client/DeltaTracker;)V"))
	private void wynndle$renderTwice(GameRenderer renderer, DeltaTracker delta) {
		renderer.renderLevel(delta);
		renderer.renderLevel(delta);
	}
}
