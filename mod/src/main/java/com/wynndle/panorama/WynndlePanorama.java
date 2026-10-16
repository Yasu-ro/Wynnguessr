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
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.Comparator;
import java.util.stream.Stream;

// One key: Minecraft's own panorama (6 cube faces, world only, no GUI),
// stitched into an 8192x4096 equirectangular image for Pannellum on
// wynndle.com. The file is named X_Z after the player's block, and sent to
// the site's review page when config/wynndle-panorama.json has a key.
public class WynndlePanorama implements ClientModInitializer {
	static final int WIDTH = 8192, HEIGHT = 4096;

	static class Config {
		String url = "https://beta.wynndle.com";
		String key = "";
	}

	static KeyMapping key;
	static volatile boolean busy;
	public static boolean capturing; // read by the mixins: hide entities and names
	static Config config = new Config();

	@Override
	public void onInitializeClient() {
		loadConfig();
		key = KeyBindingHelper.registerKeyBinding(new KeyMapping(
			"key.wynndle-panorama.capture", InputConstants.Type.KEYSYM, GLFW.GLFW_KEY_RIGHT_SHIFT, KeyMapping.Category.MISC));
		ClientTickEvents.END_CLIENT_TICK.register(mc -> {
			while (key.consumeClick()) {
				if (mc.player != null && mc.level != null && !busy) capture(mc);
			}
		});
	}

	static void capture(Minecraft mc) {
		LocalPlayer p = mc.player;
		int x = p.getBlockX(), z = p.getBlockZ();
		Path out = FabricLoader.getInstance().getGameDir().resolve("wynndle");
		Path tmp = out.resolve(".tmp-" + System.currentTimeMillis());

		// Every image faces north in its centre, whatever way the player looks.
		float yaw = p.getYRot(), yawO = p.yRotO;
		p.setYRot(180f);
		p.yRotO = 180f;
		try {
			Files.createDirectories(tmp);
			capturing = true;
			mc.grabPanoramixScreenshot(tmp.toFile());
		} catch (IOException e) {
			say(mc, Component.literal("Wynndle: " + e.getMessage()).withStyle(ChatFormatting.RED));
			return;
		} finally {
			capturing = false;
			p.setYRot(yaw);
			p.yRotO = yawO;
		}

		busy = true;
		say(mc, Component.literal("Wynndle: saving " + x + " " + z + "…").withStyle(ChatFormatting.GRAY));
		Thread t = new Thread(() -> {
			try {
				BufferedImage[] faces = readFaces(tmp.resolve("screenshots"));
				File file = freeName(out, x + "_" + z);
				writeJpeg(stitch(faces), file);
				if (config.key.isEmpty()) {
					say(mc, Component.literal("Wynndle: " + file.getName() + " saved").withStyle(ChatFormatting.GREEN));
				} else {
					String error = upload(file, x, z);
					say(mc, error == null
						? Component.literal("Wynndle: " + file.getName() + " sent").withStyle(ChatFormatting.GREEN)
						: Component.literal("Wynndle: " + file.getName() + " saved, not sent (" + error + ")").withStyle(ChatFormatting.GOLD));
				}
			} catch (Exception e) {
				say(mc, Component.literal("Wynndle: failed (" + e.getMessage() + ")").withStyle(ChatFormatting.RED));
			} finally {
				deleteTree(tmp);
				busy = false;
			}
		}, "wynndle-panorama");
		t.setDaemon(true);
		t.start();
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
	static String upload(File file, int x, int z) {
		try {
			HttpRequest req = HttpRequest.newBuilder(URI.create(config.url.replaceAll("/+$", "") + "/api/capture?x=" + x + "&z=" + z))
				.timeout(Duration.ofSeconds(60))
				.header("X-Wynndle-Key", config.key.trim())
				.header("Content-Type", "image/jpeg")
				.header("User-Agent", "WynndlePanorama/1.2")
				.POST(HttpRequest.BodyPublishers.ofFile(file.toPath()))
				.build();
			HttpResponse<String> res = HttpClient.newHttpClient().send(req, HttpResponse.BodyHandlers.ofString());
			if (res.statusCode() == 403) return "wrong key";
			return res.statusCode() == 200 ? null : "error " + res.statusCode();
		} catch (Exception e) {
			return e.getClass().getSimpleName();
		}
	}

	// Minecraft writes the faces asynchronously: wait until all six read back.
	static BufferedImage[] readFaces(Path dir) throws Exception {
		BufferedImage[] faces = new BufferedImage[6];
		long deadline = System.currentTimeMillis() + 60_000;
		for (int i = 0; i < 6; i++) {
			File f = dir.resolve("panorama_" + i + ".png").toFile();
			while (true) {
				try {
					if (f.isFile()) faces[i] = ImageIO.read(f);
				} catch (IOException ignored) {
					// still being written
				}
				if (faces[i] != null) break;
				if (System.currentTimeMillis() > deadline) throw new IOException("face " + i + " missing");
				Thread.sleep(200);
			}
		}
		return faces;
	}

	// Face order is Minecraft's: front (north here), +90° (east), +180° (south),
	// -90° (west), up, down. Vectors are (east, up, north).
	static final double[][][] FACES = {
		{{0, 0, 1}, {1, 0, 0}, {0, 1, 0}},
		{{1, 0, 0}, {0, 0, -1}, {0, 1, 0}},
		{{0, 0, -1}, {-1, 0, 0}, {0, 1, 0}},
		{{-1, 0, 0}, {0, 0, 1}, {0, 1, 0}},
		{{0, 1, 0}, {1, 0, 0}, {0, 0, -1}},
		{{0, -1, 0}, {1, 0, 0}, {0, 0, 1}},
	}; // {forward, right, screen up}

	static BufferedImage stitch(BufferedImage[] faces) {
		int size = faces[0].getWidth();
		int[][] px = new int[6][];
		for (int i = 0; i < 6; i++) px[i] = faces[i].getRGB(0, 0, size, size, null, 0, size);

		BufferedImage img = new BufferedImage(WIDTH, HEIGHT, BufferedImage.TYPE_INT_RGB);
		int[] row = new int[WIDTH];
		for (int v = 0; v < HEIGHT; v++) {
			double lat = (0.5 - (v + 0.5) / HEIGHT) * Math.PI;
			for (int u = 0; u < WIDTH; u++) {
				double lon = ((u + 0.5) / WIDTH - 0.5) * 2 * Math.PI;
				double[] d = {Math.cos(lat) * Math.sin(lon), Math.sin(lat), Math.cos(lat) * Math.cos(lon)};
				int best = 0;
				double bestDot = -2;
				for (int f = 0; f < 6; f++) {
					double dot = dot(FACES[f][0], d);
					if (dot > bestDot) { bestDot = dot; best = f; }
				}
				double sx = dot(FACES[best][1], d) / bestDot, sy = -dot(FACES[best][2], d) / bestDot;
				row[u] = bilinear(px[best], size, (sx + 1) / 2 * size - 0.5, (sy + 1) / 2 * size - 0.5);
			}
			img.setRGB(0, v, WIDTH, 1, row, 0, WIDTH);
		}
		return img;
	}

	static double dot(double[] a, double[] b) {
		return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
	}

	static int bilinear(int[] px, int size, double x, double y) {
		x = Math.max(0, Math.min(size - 1, x));
		y = Math.max(0, Math.min(size - 1, y));
		int x0 = (int) x, y0 = (int) y, x1 = Math.min(x0 + 1, size - 1), y1 = Math.min(y0 + 1, size - 1);
		double fx = x - x0, fy = y - y0;
		int a = px[y0 * size + x0], b = px[y0 * size + x1], c = px[y1 * size + x0], e = px[y1 * size + x1];
		int rgb = 0;
		for (int s = 16; s >= 0; s -= 8) {
			double top = ((a >> s) & 255) * (1 - fx) + ((b >> s) & 255) * fx;
			double bot = ((c >> s) & 255) * (1 - fx) + ((e >> s) & 255) * fx;
			rgb |= ((int) Math.round(top * (1 - fy) + bot * fy)) << s;
		}
		return rgb;
	}

	static File freeName(Path dir, String base) throws IOException {
		Files.createDirectories(dir);
		File f = dir.resolve(base + ".jpg").toFile();
		for (int n = 2; f.exists(); n++) f = dir.resolve(base + "_" + n + ".jpg").toFile();
		return f;
	}

	static void writeJpeg(BufferedImage img, File file) throws IOException {
		ImageWriter w = ImageIO.getImageWritersByFormatName("jpg").next();
		ImageWriteParam param = w.getDefaultWriteParam();
		param.setCompressionMode(ImageWriteParam.MODE_EXPLICIT);
		param.setCompressionQuality(0.95f);
		try (ImageOutputStream os = ImageIO.createImageOutputStream(file)) {
			w.setOutput(os);
			w.write(null, new IIOImage(img, null, null), param);
		} finally {
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
