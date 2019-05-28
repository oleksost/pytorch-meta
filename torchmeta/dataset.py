import torch
import warnings

from itertools import combinations
from torchvision.transforms import Compose

from torchmeta.tasks import ConcatTask
from torchmeta.transforms import FixedCategory

class ClassDataset(object):
    """Base class for a dataset of classes. Each item from a `ClassDataset` is 
    a dataset containing examples from the same class.

    Parameters
    ----------
    meta_train : bool (default: `False`)
        Use the meta-train split of the dataset. If set to `True`, then the
        arguments `meta_val` and `meta_test` must be set to `False`. Exactly one 
        of these three arguments must be set to `True`.
    meta_val : bool (default: `False`)
        Use the meta-validation split of the dataset. If set to `True`, then the 
        arguments `meta_train` and `meta_test` must be set to `False`. Exactly one 
        of these three arguments must be set to `True`.
    meta_test : bool (default: `False`)
        Use the meta-test split of the dataset. If set to `True`, then the 
        arguments `meta_train` and `meta_val` must be set to `False`. Exactly one 
        of these three arguments must be set to `True`.
    meta_split : string in {'train', 'val', 'test'}, optional
        Name of the split to use. This overrides the arguments `meta_train`, 
        `meta_val` and `meta_test`.
    class_augmentations : list of callable, optional
        A list of functions that augment the dataset with new classes. These classes 
        are transformations of existing classes. E.g. `transforms.HorizontalFlip()`.
    """
    def __init__(self, meta_train=False, meta_val=False, meta_test=False,
                 meta_split=None, class_augmentations=None):
        if meta_train + meta_val + meta_test == 0:
            if meta_split is None:
                raise ValueError('The meta-split is undefined. Use either the '
                    'argument `meta_train=True` (or `meta_val`/`meta_test`), or '
                    'the argument `meta_split="train"` (or "val"/"test").')
            elif meta_split not in ['train', 'val', 'test']:
                raise ValueError('Unknown meta-split name `{0}`. The meta-split '
                    'must be in [`train`, `val`, `test`].'.format(meta_split))
            meta_train = (meta_split == 'train')
            meta_val = (meta_split == 'val')
            meta_test = (meta_split == 'test')
        elif meta_train + meta_val + meta_test > 1:
            raise ValueError('Multiple arguments among `meta_train`, `meta_val` '
                'and `meta_test` are set to `True`. Exactly one must be set to '
                '`True`.')
        self.meta_train = meta_train
        self.meta_val = meta_val
        self.meta_test = meta_test
        self._meta_split = meta_split

        if class_augmentations is not None:
            if not isinstance(class_augmentations, list):
                raise TypeError('Unknown type for `class_augmentations`. '
                    'Expected `list`, got `{0}`.'.format(type(class_augmentations)))
            unique_augmentations = set()
            for augmentations in class_augmentations:
                for transform in augmentations:
                    if transform in unique_augmentations:
                        warnings.warn('The class augmentation `{0}` already '
                            'exists in the list of class augmentations (`{1}`). '
                            'To avoid any duplicate, this transformation is '
                            'ignored.'.format(transform, repr(transform)),
                            UserWarning, stacklevel=2)
                    unique_augmentations.add(transform)
            class_augmentations = list(unique_augmentations)
        else:
            class_augmentations = []
        self.class_augmentations = class_augmentations

    def get_class_augmentation(self, index):
        transform_index = (index // self.num_classes) - 1
        if transform_index < 0:
            return None
        return self.class_augmentations[transform_index]

    def get_transform(self, index, transform=None):
        class_transform = self.get_class_augmentation(index)
        if class_transform is None:
            return transform
        if transform is None:
            return class_transform
        return Compose([class_transform, transform])

    def get_target_transform(self, index, transform=None):
        class_transform = self.get_class_augmentation(index)
        categorical_transform = FixedCategory(class_transform)
        if transform is None:
            return categorical_transform
        return Compose([categorical_transform, transform])

    @property
    def meta_split(self):
        if self._meta_split is None:
            if self.meta_train:
                self._meta_split = 'train'
            elif self.meta_val:
                self._meta_split = 'val'
            elif self.meta_test:
                self._meta_split = 'test'
            else:
                raise NotImplementedError()
        return self._meta_split

    def __getitem__(self, index):
        raise NotImplementedError()

    @property
    def num_classes(self):
        raise NotImplementedError()

    def __len__(self):
        return self.num_classes * (len(self.class_augmentations) + 1)


class MetaDataset(object):
    """Base class for a meta-dataset.

    Parameters
    ----------
    dataset_transform : callable, optional
        A function/transform that takes a dataset (ie. a task), and returns a 
        transformed version of it. E.g. `transforms.ClassSplitter()`.
    """
    def __init__(self, dataset_transform=None):
        self.dataset_transform = dataset_transform

    def __iter__(self):
        for index in range(len(self)):
            yield self[index]

    def sample_task(self):
        index = torch.randint(len(self), size=()).item()
        return self[index]

    def __getitem__(self, index):
        raise NotImplementedError()

    def __len__(self):
        raise NotImplementedError()


class CombinationMetaDataset(MetaDataset):
    """Base class for a meta-dataset, where the classification tasks are over 
    multiple classes from a `ClassDataset`.

    Parameters
    ----------
    dataset : `ClassDataset` instance
        A dataset of classes. Each item of `dataset` is a dataset, containing 
        all the examples from the same class.
    num_classes_per_task : int
        Number of classes per tasks. This corresponds to `N` in `N-way` 
        classification.
    dataset_transform : callable, optional
        A function/transform that takes a dataset (ie. a task), and returns a 
        transformed version of it. E.g. `transforms.ClassSplitter()`.
    """
    def __init__(self, dataset, num_classes_per_task, dataset_transform=None):
        super(CombinationMetaDataset, self).__init__(dataset_transform=dataset_transform)
        if not isinstance(num_classes_per_task, int):
            raise TypeError('Unknown type for `num_classes_per_task`. Expected '
                '`int`, got `{0}`.'.format(type(num_classes_per_task)))
        self.dataset = dataset
        self.num_classes_per_task = num_classes_per_task

    def __iter__(self):
        num_classes = len(self.dataset)
        for index in combinations(num_classes, self.num_classes_per_task):
            yield self[index]

    def sample_task(self):
        import random
        index = random.sample(range(len(self.dataset)), self.num_classes_per_task)
        return self[index]

    def __getitem__(self, index):
        if isinstance(index, int):
            raise ValueError('The index of a `CombinationMetaDataset` must be '
                'a tuple of integers, and not an integer. For example, call '
                '`dataset[({0})]` to get a task with classes from 0 to {1} '
                '(got `{2}`).'.format(', '.join([str(idx)
                for idx in range(self.num_classes_per_task)]),
                self.num_classes_per_task - 1, index))
        assert len(index) == self.num_classes_per_task
        datasets = [self.dataset[i] for i in index]
        task = ConcatTask(datasets, self.num_classes_per_task)

        if self.dataset_transform is not None:
            task = self.dataset_transform(task)

        return task

    def __len__(self):
        num_classes, length = len(self.dataset), 1
        for i in range(1, self.num_classes_per_task + 1):
            length *= (num_classes - i + 1) / i
        return int(length)
