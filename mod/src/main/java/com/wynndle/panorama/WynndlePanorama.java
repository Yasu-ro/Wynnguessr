package com.wynndle.panorama;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.mojang.blaze3d.platform.InputConstants;
import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.fabricmc.fabric.api.client.keybinding.v1.KeyBindingHelper;
import net.fabricmc.loader.api.FabricLoader;
import net.minecraft.ChatFormatting;
import net.minecraft.client.KeyMapping;
import net.minecraft.client.Minecraft;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.network.chat.Component;
import org.lwjgl.glfw.GLFW;

import javax.imageio.IIOImage;
import javax.imageio.ImageIO;
import javax.imageio.ImageWriteParam;
import javax.imageio.ImageWriter;
import javax.imageio.stream.ImageOutputStream;
import java.awt.image.BufferedImage;
import java.io.File;
import java.io.IOException;
import java.io.Reader;
import java.io.Writer;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Comparator;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.stream.Stream;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

// One key: Minecraft's own panorama (6 cube faces of 4096 px, world only, no
// GUI), kept as faces in a zip: the site cuts them into multires tiles for
// Pannellum, nothing gets resampled into a blur. The zip is named X_Z after
// the player's block, and sent to the site's review page when
// config/wynndle-panorama.json has a key. A second key runs the tour of the
// spots planned on that page (see Tour).
public class WynndlePanorama implements ClientModInitializer {
	// Pannellum's cube faces, in Minecraft's order: north (front, every
	// panorama faces north), east, south, west, up, down
	static final String[] FACE_LETTERS = {"f", "r", "b", "l", "u", "d"};
	static final float NORTH = 180.5f;

	static class Config {
		String url = "https://beta.wynndle.com";
		String key = "";
		double spinSeconds = 4;  // tour: one full turn before the picture (Distant Horizons)
		double waitSeconds = 3;  // tour: then this long still
	}

	static KeyMapping key, tourKey;
	// packing, saving and sending run one after the other here, so the
	// tour can fly on as soon as a panorama is drawn
	static final ExecutorService WORKER = Executors.newSingleThreadExecutor(r -> {
		Thread t = new Thread(r, "wynndle-panorama");
		t.setDaemon(true);
		return t;
	});
	static final AtomicInteger pending = new AtomicInteger();
	public static boolean capturing; // read by the mixins: hide entities and names
	static Config config = new Config();

	@Override
	public void onInitializeClient() {
		loadConfig();
		key = KeyBindingHelper.registerKeyBinding(new KeyMapping(
			"key.wynndle-panorama.capture", InputConstants.Type.KEYSYM, GLFW.GLFW_KEY_RIGHT_SHIFT, KeyMapping.Category.MISC));
		tourKey = KeyBindingHelper.registerKeyBinding(new KeyMapping(
			"key.wynndle-panorama.tour", InputConstants.Type.KEYSYM, GLFW.GLFW_KEY_RIGHT_CONTROL, KeyMapping.Category.MISC));
		ClientTickEvents.END_CLIENT_TICK.register(mc -> {
			while (key.consumeClick()) {
				if (mc.player != null && mc.level != null && Tour.step == Tour.Step.IDLE) capture(mc, -1);
			}
			while (tourKey.consumeClick()) {
				if (mc.player != null && mc.level != null) Tour.toggle(mc);
			}
			Tour.tick(mc);
		});
	}

	// planned: id of the spot planned on the review page, or -1
	static void capture(Minecraft mc, int planned) {
		LocalPlayer p = mc.player;
		int x = p.getBlockX(), z = p.getBlockZ();
		Path out = FabricLoader.getInstance().getGameDir().resolve("wynndle");
		Path tmp = out.resolve(".tmp-" + System.currentTimeMillis());

		// Every image faces north in its centre, whatever way the player looks.
		// Not exactly north: at yaw 180.0 the face comes out without clouds or
		// Distant Horizons (in singleplayer; cause unknown, found by trying
		// 180, 180.5 and 225). Half a degree off nobody can see.
		float yaw = p.getYRot(), yawO = p.yRotO;
		try {
			Files.createDirectories(tmp);
			capturing = true;
			p.setYRot(NORTH);
			p.yRotO = NORTH;
			mc.grabPanoramixScreenshot(tmp.toFile());
		} catch (IOException e) {
			say(mc, Component.literal("Wynndle: " + e.getMessage()).withStyle(ChatFormatting.RED));
			return;
		} finally {
			capturing = false;
			p.setYRot(yaw);
			p.yRotO = yawO;
		}

		pending.incrementAndGet();
		WORKER.execute(() -> {
			try {
				File file = freeName(out, x + "_" + z);
				try {
					packFaces(tmp.resolve("screenshots"), file);
				} catch (Exception e) {
					file.delete(); // half a zip helps nobody
					throw e;
				}
				if (config.key.isEmpty()) {
					say(mc, Component.literal("Wynndle: " + file.getName() + " saved").withStyle(ChatFormatting.GREEN));
				} else {
					String error = upload(file, x, z, planned);
					say(mc, error == null
						? Component.literal("Wynndle: " + file.getName() + " sent").withStyle(ChatFormatting.GREEN)
						: Component.literal("Wynndle: " + file.getName() + " saved, not sent (" + error + ")").withStyle(ChatFormatting.GOLD));
				}
			} catch (Exception e) {
				say(mc, Component.literal("Wynndle: failed (" + e.getMessage() + ")").withStyle(ChatFormatting.RED));
			} finally {
				deleteTree(tmp);
				pending.decrementAndGet();
			}
		});
	}

	// The file is created empty on the first start; the key goes in by hand.
	static void loadConfig() {
		Path path = FabricLoader.getInstance().getConfigDir().resolve("wynndle-panorama.json");
		Gson gson = new GsonBuilder().setPrettyPrinting().create();
		try {
			if (Files.exists(path)) {
				try (Reader r = Files.newBufferedReader(path)) {
					Config c = gson.fromJson(r, Config.class);
					if (c != null && c.url != null && c.key != null) config = c;
				}
			} else {
				try (Writer w = Files.newBufferedWriter(path)) {
					gson.toJson(config, w);
				}
			}
		} catch (Exception ignored) {
			// a broken file only means no sending: the panoramas are still saved
		}
	}

	// Returns null when the site has it, else why not (the file stays saved).
	static String upload(File file, int x, int z, int planned) {
		try {
			HttpRequest req = Tour.request("/api/capture?x=" + x + "&z=" + z + (planned >= 0 ? "&planned=" + planned : ""))
				.header("Content-Type", "application/zip")
				.POST(HttpRequest.BodyPublishers.ofFile(file.toPath()))
				.build();
			HttpResponse<String> res = HttpClient.newHttpClient().send(req, HttpResponse.BodyHandlers.ofString());
			if (res.statusCode() == 403) return "wrong key";
			return res.statusCode() == 200 ? null : "error " + res.statusCode();
		} catch (Exception e) {
			return e.getClass().getSimpleName();
		}
	}

	// Minecraft writes the faces asynchronously: each is read back once it is
	// complete, then goes into the zip as a JPEG, one at a time (64 MB each).
	static void packFaces(Path dir, File zip) throws Exception {
		long deadline = System.currentTimeMillis() + 60_000;
		try (ZipOutputStream out = new ZipOutputStream(Files.newOutputStream(zip.toPath()))) {
			out.setLevel(0); // JPEGs do not compress further
			for (int i = 0; i < 6; i++) {
				File f = dir.resolve("panorama_" + i + ".png").toFile();
				BufferedImage face = null;
				while (face == null) {
					try {
						if (f.isFile()) face = ImageIO.read(f);
					} catch (IOException ignored) {
						// still being written
					}
					if (face != null) break;
					if (System.currentTimeMillis() > deadline) throw new IOException("face " + i + " missing");
					Thread.sleep(200);
				}
				out.putNextEntry(new ZipEntry(FACE_LETTERS[i] + ".jpg"));
				writeJpeg(opaque(face), out);
				out.closeEntry();
			}
		}
	}

	// Minecraft's PNGs have an alpha channel, which Java's JPEG writer refuses
	// ("Bogus input colorspace")
	static BufferedImage opaque(BufferedImage img) {
		if (img.getType() == BufferedImage.TYPE_INT_RGB) return img;
		BufferedImage rgb = new BufferedImage(img.getWidth(), img.getHeight(), BufferedImage.TYPE_INT_RGB);
		java.awt.Graphics2D g = rgb.createGraphics();
		g.drawImage(img, 0, 0, null);
		g.dispose();
		return rgb;
	}

	static File freeName(Path dir, String base) throws IOException {
		Files.createDirectories(dir);
		File f = dir.resolve(base + ".zip").toFile();
		for (int n = 2; f.exists(); n++) f = dir.resolve(base + "_" + n + ".zip").toFile();
		return f;
	}

	static void writeJpeg(BufferedImage img, java.io.OutputStream to) throws IOException {
		ImageWriter w = ImageIO.getImageWritersByFormatName("jpg").next();
		ImageWriteParam param = w.getDefaultWriteParam();
		param.setCompressionMode(ImageWriteParam.MODE_EXPLICIT);
		param.setCompressionQuality(0.95f);
		// the stream must stay open: the zip goes on after this face
		ImageOutputStream os = ImageIO.createImageOutputStream(new java.io.FilterOutputStream(to) {
			@Override public void write(byte[] b, int off, int len) throws IOException { out.write(b, off, len); }
			@Override public void close() throws IOException { flush(); }
		});
		try {
			w.setOutput(os);
			w.write(null, new IIOImage(img, null, null), param);
		} finally {
			os.close();
			w.dispose();
		}
	}

	static void deleteTree(Path dir) {
		try (Stream<Path> s = Files.walk(dir)) {
			s.sorted(Comparator.reverseOrder()).forEach(q -> q.toFile().delete());
		} catch (IOException ignored) {
		}
	}

	static void say(Minecraft mc, Component msg) {
		mc.execute(() -> {
			if (mc.player != null) mc.player.displayClientMessage(msg, false);
		});
	}
}
