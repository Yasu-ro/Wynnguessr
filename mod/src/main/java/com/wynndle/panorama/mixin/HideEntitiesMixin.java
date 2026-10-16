package com.wynndle.panorama.mixin;

import com.wynndle.panorama.WynndlePanorama;
import net.minecraft.client.renderer.culling.Frustum;
import net.minecraft.client.renderer.entity.EntityRenderDispatcher;
import net.minecraft.world.entity.Display;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.entity.decoration.ArmorStand;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

// During a capture: no mobs, NPCs, players or pets, and no floating text.
// Armor stands stay (Wynncraft decorates with them), only their names go.
@Mixin(EntityRenderDispatcher.class)
public class HideEntitiesMixin {
	@Inject(method = "shouldRender", at = @At("HEAD"), cancellable = true)
	private <E extends Entity> void wynndle$hide(E entity, Frustum frustum, double x, double y, double z, CallbackInfoReturnable<Boolean> cir) {
		if (WynndlePanorama.capturing
			&& ((entity instanceof LivingEntity && !(entity instanceof ArmorStand)) || entity instanceof Display.TextDisplay)) {
			cir.setReturnValue(false);
		}
	}
}
