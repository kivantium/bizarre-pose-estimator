



from _util.util_v1 import * ; import _util.util_v1 as uutil
from _util.pytorch_v1 import * ; import _util.pytorch_v1 as utorch
from _util.twodee_v0 import * ; import _util.twodee_v0 as u2d

import _util.keypoints_v0 as ukey
import numpy as np


parser = argparse.ArgumentParser()
parser.add_argument('fn_img')
parser.add_argument('fn_model')
args = parser.parse_args()
img = I(args.fn_img)


######################## SEGMENTER ########################

from _train.character_bg_seg.models.alaska import Model as CharacterBGSegmenter
model_segmenter = CharacterBGSegmenter.load_from_checkpoint(
    './_train/character_bg_seg/runs/eyeless_alaska_vulcan0000/checkpoints/'
    'epoch=0096-val_f1=0.9508-val_loss=0.0483.ckpt'
)

def abbox(img, thresh=0.5, allow_empty=False):
    # get bbox from alpha image, at threshold
    img = I(img).np()
    assert len(img) in [1,4], 'image must be mode L or RGBA'
    a = img[-1] > thresh
    xlim = np.any(a, axis=1).nonzero()[0]
    ylim = np.any(a, axis=0).nonzero()[0]
    if len(xlim)==0 and allow_empty: xlim = np.asarray([0, a.shape[0]])
    if len(ylim)==0 and allow_empty: ylim = np.asarray([0, a.shape[1]])
    axmin,axmax = max(int(xlim.min()-1),0), min(int(xlim.max()+1),a.shape[0])
    aymin,aymax = max(int(ylim.min()-1),0), min(int(ylim.max()+1),a.shape[1])
    return [(axmin,aymin), (axmax-axmin,aymax-aymin)]

def infer_segmentation(self, images, bbox_thresh=0.5, return_more=True):
    anss = []
    _size = self.hparams.largs.bg_seg.size
    self.eval()
    for img in images:
        oimg = img
        # img = a2bg(resize_min(img, _size).convert('RGBA'),1).convert('RGB')
        img = I(img).resize_min(_size).convert('RGBA').alpha_bg(1).convert('RGB').pil()
        timg = TF.to_tensor(img)[None].to(self.device)
        with torch.no_grad():
            out = self(timg)
        ans = TF.to_pil_image(out['softmax'][0,1].float().cpu()).resize(oimg.size[::-1])
        ans = {'segmentation': I(ans)}
        ans['bbox'] = abbox(ans['segmentation'], thresh=bbox_thresh, allow_empty=True)
        anss.append(ans)
    return anss


######################## POSE ESTIMATOR ########################

if 'feat_concat' in args.fn_model:
    from _train.character_pose_estim.models.passup import Model as CharacterPoseEstimator
elif 'feat_match' in args.fn_model:
    from _train.character_pose_estim.models.fermat import Model as CharacterPoseEstimator
else:
    assert 0, 'must use one of the provided pose estimation models'
model_pose = CharacterPoseEstimator.load_from_checkpoint(args.fn_model, strict=False)

def infer_pose(self, segmenter, images, smoothing=0.1, pad_factor=1):
    self.eval()
    try:
        largs = self.hparams.largs.adds_keypoints
    except:
        largs = self.hparams.largs.danbooru_coco
    _s = largs.size
    _p = _s * largs.padding
    anss = []
    segs = infer_segmentation(segmenter, images)
    for img,seg in zip(images,segs):
        # segment
        oimg = img
        ans = {
            'segmentation_output': seg,
        }
        bbox = seg['bbox']
        cb = u2d.cropbox_sequence([
            # crop to bbox, resize to square, pad sides
            [bbox[0], bbox[1], bbox[1]],
            resize_square_dry(bbox[1], _s),
            [-_p*pad_factor/2, _s+_p*pad_factor, _s],
        ])
        icb = u2d.cropbox_inverse(oimg.size, *cb)
        img = u2d.cropbox(img, *cb)
        img = img.convert('RGBA').alpha(0).convert('RGB')
        ans['bbox'] = bbox
        ans['cropbox'] = cb
        ans['cropbox_inverse'] = icb
        ans['input_image'] = img
        
        # pose estim
        timg = img.tensor()[None].to(self.device)
        with torch.no_grad():
            out = self(timg, smoothing=smoothing, return_more=True)
        ans['out'] = out
        
        # post-process keypoints
        kps = out['keypoints'][0].cpu().numpy()
        kps = u2d.cropbox_points(kps, *icb)
        ans['keypoints'] = kps
        
        anss.append(ans)
    return anss

######################## MODEL FORWARD ########################

def _visualize(image=None, bbox=None, keypoints=None):
    v = image
    if bbox is not None:
        v = v.rect(*bbox, c='r', w=2)
    if keypoints is not None:
        if isinstance(keypoints, dict):
            keypoints = np.asarray([keypoints[k] for k in ukey.coco_keypoints])
        for (a,b),c in zip(ukey.coco_parts, ukey.coco_part_colors):
            v = v.line(keypoints[a], keypoints[b], w=5, c=c)
        keypoints = keypoints[:len(ukey.coco_keypoints)]
        for kp in keypoints:
            v = v.dot(kp, s=5, c='r')
    return v

ans = infer_pose(model_pose, model_segmenter, [img,])

bbox = ans[0]['bbox']
print(f'bounding box\n\ttop-left: {bbox[0]}\n\tsize: {bbox[1]}')
print()

print('keypoints')
v = img
for k,(x,y) in zip(ukey.coco_keypoints, ans[0]['keypoints']):
    print((f'\t({x:.2f}, {y:.2f})'), k)
print()
d = scipy.spatial.distance.pdist(u2d.cropbox_points(ans[0]['keypoints'], *ans[0]['cropbox']))
np.save('./_samples/results.npy', [ans[0]['keypoints'], ans[0]['cropbox'], d])

_visualize(img, ans[0]['bbox'], ans[0]['keypoints']).save('./_samples/character_pose_estim.png')
print('output saved to ./_samples/character_pose_estim.png')




