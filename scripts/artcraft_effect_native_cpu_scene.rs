// Temporary external EffectCraft CPU scene. Not submitted to upstream and not a second renderer.
use effectcraft_color::Label;
use effectcraft_project::{build, Comp, ItemKind, LayerSource, Project, Solid};
use effectcraft_time::{FrameRate, Tick};
use effectcraft_render::render_frame;

fn put_solid(p: &mut Project, comp: &Comp, name: &str, color: [f32; 3], w: u32, h: u32) -> effectcraft_project::Layer {
    let sid = p.add_item(
        name, Label::Red, None,
        ItemKind::Solid(Solid { color, width: w, height: h, pixel_aspect: 1.0 })
    );
    build::layer(p, comp, name, LayerSource::Solid { item: sid }, (w, h), None)
}

fn main() {
    let mut p = Project::default();
    p.settings.bit_depth = effectcraft_project::BitDepth::Bpc32;
    let comp = Comp::new(200, 100, FrameRate::FPS_30, Tick::from_seconds_f64(2.0));
    let cid = p.add_item("BR-Research-Scene", Label::Sandstone, None, ItemKind::Comp(comp.clone().into()));
    let top = put_solid(&mut p, &comp, "Green overlay", [0.0, 1.0, 0.0], 60, 40);
    let bg = put_solid(&mut p, &comp, "Red background", [1.0, 0.0, 0.0], 200, 100);
    p.comp_mut(cid).expect("test comp present").layers = vec![top, bg];
    // THIS is the real upstream EffectCraft renderer, not a fabricated frame.
    let image = render_frame(&p, cid, Tick::ZERO, 1.0);
    assert_eq!((image.width, image.height), (200, 100));
    let mut bytes = b"P6\n200 100\n255\n".to_vec();
    let mut distinct = std::collections::BTreeSet::new();
    for y in 0..image.height {
        for x in 0..image.width {
            let px = image.get(x as i64, y as i64);
            let rgb = [
                (px[0].clamp(0.0, 1.0) * 255.0).round() as u8,
                (px[1].clamp(0.0, 1.0) * 255.0).round() as u8,
                (px[2].clamp(0.0, 1.0) * 255.0).round() as u8,
            ];
            distinct.insert(rgb);
            bytes.extend_from_slice(&rgb);
        }
    }
    assert!(distinct.len() > 1, "native render produced a flat frame");
    let out = std::env::args().nth(1).expect("output path argument");
    std::fs::write(&out, bytes).expect("write bounded PPM in isolated volume");
    println!("EFFECTCRAFT_REAL_CPU_RENDER_FRAME=PASS width={} height={} colors={}", image.width, image.height, distinct.len());
}
