import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const manifest = JSON.parse(
  readFileSync(resolve(process.cwd(), 'public/assets/manifest.json'), 'utf8'),
) as {
  global_texture: {
    file: string
    public_url: string
    dimensions_pixels: number[]
    file_size_bytes: number
    sha256: string
    use: string
  }
}

describe('packaged lunar texture asset', () => {
  it('matches the checked-in asset to its source and display metadata', () => {
    const asset = readFileSync(resolve(process.cwd(), 'public/assets/lroc_color_2k.jpg'))
    const hash = createHash('sha256').update(asset).digest('hex')

    expect(asset.subarray(0, 2)).toEqual(Buffer.from([0xff, 0xd8]))
    expect(manifest.global_texture.file).toBe('lroc_color_2k.jpg')
    expect(manifest.global_texture.public_url).toBe('/assets/lroc_color_2k.jpg')
    expect(manifest.global_texture.dimensions_pixels).toEqual([2048, 1024])
    expect(asset.byteLength).toBe(manifest.global_texture.file_size_bytes)
    expect(hash).toBe(manifest.global_texture.sha256)
    expect(manifest.global_texture.use).toMatch(/not numerical elevation data/i)
  })
})
